# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Task implementations + a synchronous executor.

`execute()` is the single entry point used by BOTH the inline dispatcher
(local) and the Arq worker (cloud). It owns its own DB session, transitions the
job through running -> success/error, and never raises into the caller — the
outcome is always recorded on the Job row.

Tasks read judge credentials from the vault-backed DB at run time; secrets are
never passed across the queue.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Problem, User


def _run_sync(db: Session, user: User, params: dict) -> dict:
    from ..services.sync import get_credentials, sync_user_problems

    judge = params["judge"]
    account = params.get("account")
    creds = get_credentials(db, user, judge, account) or {
        "username": account or params.get("username")
    }
    return sync_user_problems(db, user, judge, creds, account).model_dump()


def _run_backfill(db: Session, user: User, params: dict) -> dict:
    from ..services import submissions as sub_svc

    return sub_svc.backfill_all(
        db, user, judge=params.get("judge"), force=bool(params.get("force"))
    )


def _run_insight(db: Session, user: User, params: dict) -> dict:
    from ..services.insights import generate_insight

    problem = db.get(Problem, params["problem_id"])
    if not problem or problem.user_id != user.id:
        raise ValueError("Problem not found.")
    text = generate_insight(
        problem.title, problem.difficulty, problem.topics, problem.url, user_id=user.id
    )
    problem.approach = text
    db.commit()
    return {"id": problem.id, "approach": text}


TASK_REGISTRY: dict[str, Callable[[Session, User, dict], dict]] = {
    "sync": _run_sync,
    "backfill": _run_backfill,
    "insight": _run_insight,
}


def execute(kind: str, job_id: str, user_id: int, params: dict) -> None:
    """Run a task to completion, recording the outcome on the Job row.

    Safe to call from any thread/process; opens and closes its own session.
    """
    from ..services import jobs as job_svc

    db = SessionLocal()
    try:
        fn = TASK_REGISTRY.get(kind)
        if fn is None:
            job_svc.mark_error(db, job_id, f"Unknown task kind: {kind}")
            return
        user = db.get(User, user_id)
        if user is None:
            job_svc.mark_error(db, job_id, "User not found.")
            return
        job_svc.mark_running(db, job_id)
        result = fn(db, user, params)
        job_svc.mark_success(db, job_id, result)
    except Exception as exc:  # noqa: BLE001 — record failure, never crash the worker
        db.rollback()
        job_svc.mark_error(db, job_id, str(exc))
    finally:
        db.close()
