# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Dispatch background work either inline (local) or onto Arq (cloud).

`dispatch()` creates a Job, then:
  - workers enabled  (REDIS_URL set): enqueues the task on Arq and returns the
    still-`queued` job; the client polls GET /api/jobs/{id}.
  - workers disabled (local default): runs the task inline and returns the
    already-terminal job, so the response carries the result immediately.

Either way the API contract is identical: callers get a Job back.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Job, User
from ..services import jobs as job_svc


def dispatch(db: Session, user: User, kind: str, params: dict) -> Job:
    settings = get_settings()
    job = job_svc.new_job(db, user, kind)

    if settings.workers_enabled:
        _enqueue(settings.redis_url, kind, job.id, user.id, params)
    else:
        from .tasks import execute

        execute(kind, job.id, user.id, params)

    db.refresh(job)
    return job


def _enqueue(redis_url: str, kind: str, job_id: str, user_id: int, params: dict) -> None:
    """Push a task onto Arq from a synchronous request handler."""
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "REDIS_URL is set but 'arq' is not installed. Install it to run workers."
        ) from exc

    async def _push() -> None:
        pool = await create_pool(RedisSettings.from_dsn(redis_url))
        try:
            await pool.enqueue_job("run_task", kind, job_id, user_id, params)
        finally:
            await pool.aclose()

    asyncio.run(_push())
