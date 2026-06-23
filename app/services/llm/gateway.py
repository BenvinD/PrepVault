# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""The LLM gateway boundary.

Every AI feature in PrepVault depends ONLY on `LLMGatewayClient`. Nothing else
imports an LLM SDK or makes raw HTTP calls to a model provider. The current
implementation speaks an OpenAI-compatible request/response shape to a
configurable base URL, so we can point at OpenAI / OpenRouter / Groq / a local
server today, and at our own gateway service tomorrow, with zero changes to
callers.

Design seams left intentionally simple here (the real logic lives in the
gateway service):
  - metering hooks: every call emits a `UsageEvent` to a pluggable sink
  - per-user rate limits / provider failover: not implemented here
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence

import requests

from ...config import Settings, get_settings
from .types import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    Usage,
    UsageEvent,
)


class LLMGatewayError(RuntimeError):
    """Raised when the gateway is unconfigured or a request fails."""


# A metering sink consumes usage events. Default is a no-op; the gateway
# service (or an observability layer) can install a real one later.
UsageSink = Callable[[UsageEvent], None]


def _noop_sink(_: UsageEvent) -> None:
    return None


class LLMGatewayClient:
    """OpenAI-compatible HTTP client for the LLM gateway boundary."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        embed_model: str,
        timeout: float = 60.0,
        usage_sink: UsageSink | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._embed_model = embed_model
        self._timeout = timeout
        self._emit = usage_sink or _noop_sink

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, *, usage_sink: UsageSink | None = None
    ) -> "LLMGatewayClient":
        settings = settings or get_settings()
        return cls(
            base_url=settings.effective_gateway_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            embed_model=settings.llm_embed_model,
            usage_sink=usage_sink,
        )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    # -- public API -------------------------------------------------------

    def complete(
        self,
        messages: Sequence[ChatMessage | dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 256,
        user_id: int | None = None,
        **opts,
    ) -> CompletionResult:
        self._require_key()
        model = model or self._model
        payload = {
            "model": model,
            "messages": [self._as_message(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **opts,
        }
        started = time.perf_counter()
        data = self._post("/chat/completions", payload)
        latency_ms = (time.perf_counter() - started) * 1000

        try:
            text = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise LLMGatewayError("Malformed completion response from gateway.") from exc

        usage = self._usage(data)
        self._emit(UsageEvent(kind="complete", model=model, usage=usage,
                              latency_ms=latency_ms, user_id=user_id))
        return CompletionResult(text=text, model=model, usage=usage)

    def embed(
        self,
        texts: Iterable[str],
        *,
        model: str | None = None,
        user_id: int | None = None,
    ) -> EmbeddingResult:
        self._require_key()
        model = model or self._embed_model
        inputs = list(texts)
        payload = {"model": model, "input": inputs}
        started = time.perf_counter()
        data = self._post("/embeddings", payload)
        latency_ms = (time.perf_counter() - started) * 1000

        try:
            items = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            raise LLMGatewayError("Malformed embedding response from gateway.") from exc

        usage = self._usage(data)
        self._emit(UsageEvent(kind="embed", model=model, usage=usage,
                              latency_ms=latency_ms, user_id=user_id))
        return EmbeddingResult(vectors=vectors, model=model, usage=usage)

    # -- internals --------------------------------------------------------

    def _require_key(self) -> None:
        if not self._api_key:
            raise LLMGatewayError(
                "LLM gateway is not configured. Set LLM_API_KEY (and optionally "
                "LLM_GATEWAY_URL) to enable AI features."
            )

    def _post(self, path: str, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                f"{self._base_url}{path}", json=payload, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            # Never leak the API key or full payload in error messages.
            raise LLMGatewayError(f"LLM gateway request failed: {exc}") from exc

    @staticmethod
    def _as_message(m: ChatMessage | dict) -> dict:
        if isinstance(m, ChatMessage):
            return m.model_dump()
        return {"role": m["role"], "content": m["content"]}

    @staticmethod
    def _usage(data: dict) -> Usage:
        raw = data.get("usage") or {}
        return Usage(
            prompt_tokens=raw.get("prompt_tokens", 0),
            completion_tokens=raw.get("completion_tokens", 0),
            total_tokens=raw.get("total_tokens", 0),
        )


def get_gateway(usage_sink: UsageSink | None = None) -> LLMGatewayClient:
    """Convenience factory used by services/workers."""
    return LLMGatewayClient.from_settings(usage_sink=usage_sink)
