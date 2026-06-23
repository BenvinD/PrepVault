# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Resilience for outbound judge calls.

Three concerns, applied at the service boundary where the per-user context
lives (providers stay user-agnostic):

  - Rate limiting: a per-(user, judge) token bucket so sync/backfill can never
    burst against a judge and get the user's account flagged. Redis-backed when
    a worker/Redis is configured (shared across replicas), in-process otherwise.
  - Circuit breaking: per-judge breaker that trips after repeated transient
    failures and short-circuits for a cooldown, so we stop hammering a judge
    that's erroring. In-process (per replica) — a fine Phase-0 seam.
  - Backoff: exponential backoff with jitter, retrying only transient errors
    (timeouts, connection drops, 429/5xx). Logical errors (bad cookie, GraphQL
    errors) are not retried.

`guard_judge_call(judge, fn, user_id=...)` composes all three around a single
idempotent provider operation.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import TypeVar

import requests

from ..config import Settings, get_settings

T = TypeVar("T")

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class RateLimitExceeded(RuntimeError):
    pass


class CircuitOpenError(RuntimeError):
    pass


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code in _TRANSIENT_STATUS
    return False


# --------------------------------------------------------------------------
# Rate limiting (token bucket)
# --------------------------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    ts: float


class InMemoryRateLimiter:
    """Process-local token bucket keyed by (user_id, judge)."""

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = capacity
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, user_id: int | None, judge: str, *, max_wait: float = 10.0) -> None:
        key = f"{user_id}:{judge}"
        deadline = time.monotonic() + max_wait
        while True:
            with self._lock:
                now = time.monotonic()
                bucket = self._buckets.get(key) or _Bucket(self._capacity, now)
                elapsed = max(0.0, now - bucket.ts)
                bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._rate)
                bucket.ts = now
                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    self._buckets[key] = bucket
                    return
                deficit = 1 - bucket.tokens
                wait = deficit / self._rate if self._rate > 0 else max_wait
                self._buckets[key] = bucket
            if time.monotonic() + wait > deadline:
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {judge}; try again shortly."
                )
            time.sleep(min(wait, 0.5))


# Atomic token-bucket in Redis (shared across replicas). Returns [allowed, wait_ms].
_REDIS_TOKEN_BUCKET = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then tokens = capacity; ts = now end
local delta = math.max(0, now - ts)
tokens = math.min(capacity, tokens + delta * rate)
local allowed = 0
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait = math.ceil((1 - tokens) / rate * 1000)
end
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 1)
return {allowed, wait}
"""


class RedisRateLimiter:
    """Token bucket backed by Redis, shared across API/worker replicas."""

    def __init__(self, redis_url: str, rate: float, capacity: int) -> None:
        import redis  # lazy: only needed when Redis is configured

        self._client = redis.Redis.from_url(redis_url)
        self._script = self._client.register_script(_REDIS_TOKEN_BUCKET)
        self._rate = rate
        self._capacity = capacity

    def acquire(self, user_id: int | None, judge: str, *, max_wait: float = 10.0) -> None:
        key = f"prepvault:rl:{user_id}:{judge}"
        deadline = time.monotonic() + max_wait
        while True:
            allowed, wait_ms = self._script(
                keys=[key], args=[self._rate, self._capacity, time.time()]
            )
            if int(allowed) == 1:
                return
            wait = int(wait_ms) / 1000.0
            if time.monotonic() + wait > deadline:
                raise RateLimitExceeded(
                    f"Rate limit exceeded for {judge}; try again shortly."
                )
            time.sleep(min(wait, 0.5))


@lru_cache
def get_rate_limiter():
    settings = get_settings()
    if settings.redis_url:
        try:
            return RedisRateLimiter(
                settings.redis_url, settings.judge_rate_per_sec, settings.judge_rate_burst
            )
        except Exception:  # noqa: BLE001 — fall back to in-process if redis import/conn fails
            pass
    return InMemoryRateLimiter(settings.judge_rate_per_sec, settings.judge_rate_burst)


# --------------------------------------------------------------------------
# Circuit breaker (per judge, in-process)
# --------------------------------------------------------------------------


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(self, fail_threshold: int, reset_seconds: float) -> None:
        self._threshold = fail_threshold
        self._reset = reset_seconds
        self._states: dict[str, _CircuitState] = {}
        self._lock = threading.Lock()

    def before(self, judge: str) -> None:
        with self._lock:
            st = self._states.get(judge)
            if not st or st.opened_at is None:
                return
            if time.monotonic() - st.opened_at >= self._reset:
                # Cooldown elapsed: half-open — allow a trial call.
                st.opened_at = None
                st.failures = 0
                return
            raise CircuitOpenError(
                f"{judge} is temporarily unavailable (circuit open); try again shortly."
            )

    def on_success(self, judge: str) -> None:
        with self._lock:
            self._states[judge] = _CircuitState()

    def on_failure(self, judge: str) -> None:
        with self._lock:
            st = self._states.setdefault(judge, _CircuitState())
            st.failures += 1
            if st.failures >= self._threshold:
                st.opened_at = time.monotonic()


@lru_cache
def get_circuit_breaker() -> CircuitBreaker:
    settings = get_settings()
    return CircuitBreaker(settings.circuit_fail_threshold, settings.circuit_reset_seconds)


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------


def guard_judge_call(
    judge: str,
    fn: Callable[[], T],
    *,
    user_id: int | None = None,
    settings: Settings | None = None,
) -> T:
    """Run an idempotent judge operation with rate limit + circuit + backoff."""
    settings = settings or get_settings()
    judge = (judge or "").lower()
    limiter = get_rate_limiter()
    breaker = get_circuit_breaker()

    breaker.before(judge)
    limiter.acquire(user_id, judge)

    attempts = max(1, settings.judge_max_retries)
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            if is_transient(exc):
                breaker.on_failure(judge)
                last_exc = exc
                if attempt < attempts - 1:
                    delay = (2 ** attempt) * 0.5 + random.uniform(0, 0.3)
                    time.sleep(delay)
                    continue
            raise
        else:
            breaker.on_success(judge)
            return result
    assert last_exc is not None
    raise last_exc
