# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Sync + stats + insight endpoints.

Slow/external work (sync, backfill, insight) is dispatched as a background job
and returns a Job envelope. In local mode the job runs inline and comes back
already `success` with its result embedded; in cloud mode it returns `queued`
and the client polls GET /api/jobs/{id}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Problem, User
from ..providers import get_provider
from ..schemas import JobOut, StatsOut, SyncRequest, UnsyncRequest
from ..services import jobs as job_svc
from ..services.activity import compute_activity
from ..services.stats import compute_stats
from ..services.sync import list_accounts, store_credentials, unsync_account
from ..workers import dispatch

router = APIRouter(prefix="/api", tags=["sync"])


def _as_job_out(job) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        result=job_svc.result_dict(job),
        error=job.error,
    )


@router.post("/sync", response_model=JobOut)
def run_sync(
    payload: SyncRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    session = payload.session_cookie or payload.leetcode_session
    credentials = {
        "session_cookie": session,
        "leetcode_session": payload.leetcode_session or payload.session_cookie,
        "csrftoken": payload.csrftoken,
        "username": payload.username,
    }
    try:
        provider = get_provider(payload.judge)
    except KeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # A username is mandatory for every syncable judge: it labels the account so
    # problems are attributed to it and can be unsynced independently.
    username = (payload.username or "").strip()
    if provider.syncable and not username:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A username is required to sync {provider.label}.",
        )
    account = username or provider.resolve_account(credentials)

    # Persist credentials (vault-encrypted) up front so the worker can decrypt
    # them at fetch time — secrets never travel across the queue.
    store_credentials(db, user, payload.judge, credentials, account)
    db.commit()
    job = dispatch(
        db,
        user,
        "sync",
        {"judge": payload.judge, "username": payload.username, "account": account},
    )
    return _as_job_out(job)


@router.get("/sync/accounts")
def get_accounts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    return list_accounts(db, user)


@router.post("/sync/unsync")
def remove_account(
    payload: UnsyncRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return unsync_account(db, user, payload.judge, payload.account)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/stats", response_model=StatsOut)
def get_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StatsOut:
    return compute_stats(db, user.id)


@router.get("/activity")
def get_activity(
    year: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return compute_activity(db, user.id, year)


@router.post("/sync/backfill", response_model=JobOut)
def backfill_submissions(
    judge: str | None = None,
    force: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    job = dispatch(db, user, "backfill", {"judge": judge, "force": force})
    return _as_job_out(job)


@router.post("/problems/{problem_id}/insight", response_model=JobOut)
def make_insight(
    problem_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobOut:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    job = dispatch(db, user, "insight", {"problem_id": problem_id})
    return _as_job_out(job)
