# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Submission viewing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Problem, Submission, User
from ..schemas import ManualSubmissionIn, SubmissionCodeOut
from ..services import submissions as svc
from ..services.presentation import unify_problem, unify_submission

router = APIRouter(prefix="/api", tags=["submissions"])


@router.get("/problems/{problem_id}/submissions")
def get_submissions(
    problem_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    try:
        subs = svc.fetch_and_store(db, user, problem, refresh=refresh)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.refresh(problem)
    return {
        "problem": unify_problem(problem),
        "submissions": [unify_submission(s) for s in subs],
    }


@router.post("/problems/{problem_id}/submissions/manual")
def add_manual_submission(
    problem_id: int,
    payload: ManualSubmissionIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    sub = svc.add_manual_submission(
        db,
        user,
        problem,
        code=payload.code,
        lang=payload.lang,
        status=payload.status,
        runtime=payload.runtime,
        memory=payload.memory,
        submitted_at=payload.submitted_at,
    )
    db.refresh(problem)
    return {
        "problem": unify_problem(problem),
        "submission": unify_submission(sub),
    }


@router.get("/submissions/{submission_id}/code", response_model=SubmissionCodeOut)
def get_submission_code(
    submission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubmissionCodeOut:
    submission = db.get(Submission, submission_id)
    if not submission or submission.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    problem = db.get(Problem, submission.problem_id)
    try:
        submission = svc.fetch_code(db, user, problem, submission)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return SubmissionCodeOut(
        id=submission.id,
        external_id=submission.external_id,
        lang=submission.lang,
        code=submission.code,
    )
