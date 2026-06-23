# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Arq worker entry point (cloud mode).

Run with:  arq app.workers.queue.WorkerSettings

The worker consumes tasks enqueued by the API. Our task code is synchronous
(requests + sync SQLAlchemy), so it runs in a thread to avoid blocking the
event loop, per the "never block the loop on I/O" guardrail.

This module is only imported by the Arq CLI in cloud mode, so importing arq at
module load is fine — local mode never touches it.
"""

from __future__ import annotations

import asyncio

from arq.connections import RedisSettings

from ..config import get_settings


async def run_task(ctx, kind: str, job_id: str, user_id: int, params: dict) -> None:
    from .tasks import execute

    await asyncio.to_thread(execute, kind, job_id, user_id, params)


def _redis_settings() -> RedisSettings:
    settings = get_settings()
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL must be set to run the Arq worker.")
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    """Arq worker configuration."""

    functions = [run_task]
    redis_settings = _redis_settings()
