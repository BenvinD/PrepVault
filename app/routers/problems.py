# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Problem CRUD + revision actions."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Problem, User
from ..schemas import ProblemCreate, ProblemUpdate
from ..services.presentation import unify_problem
from ..services.revision import compute_next_revision

router = APIRouter(prefix="/api/problems", tags=["problems"])


@router.get("")
def list_problems(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: str | None = Query(None, description="Search title/topics"),
    difficulty: str | None = None,
    due: bool = False,
) -> list[dict]:
    stmt = select(Problem).where(Problem.user_id == user.id)
    if difficulty:
        stmt = stmt.where(Problem.difficulty == difficulty)
    if due:
        stmt = stmt.where(Problem.next_revision.is_not(None), Problem.next_revision <= date.today())
    stmt = stmt.order_by(Problem.updated_at.desc())
    problems = db.execute(stmt).scalars().all()
    if q:
        ql = q.lower()
        problems = [p for p in problems if ql in (p.title or "").lower() or ql in (p.topics or "").lower()]
    return [unify_problem(p) for p in problems]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_problem(
    payload: ProblemCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    problem = Problem(user_id=user.id, source="manual", **payload.model_dump())
    problem.next_revision = compute_next_revision(problem)
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return unify_problem(problem)


@router.patch("/{problem_id}")
def update_problem(
    problem_id: int,
    payload: ProblemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(problem, key, value)
    problem.next_revision = compute_next_revision(problem)
    db.commit()
    db.refresh(problem)
    return unify_problem(problem)


@router.post("/{problem_id}/revised")
def mark_revised(
    problem_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    problem.last_revised = date.today()
    problem.next_revision = compute_next_revision(problem)
    db.commit()
    db.refresh(problem)
    return unify_problem(problem)


@router.delete("/{problem_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_problem(
    problem_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    problem = db.get(Problem, problem_id)
    if not problem or problem.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found.")
    db.delete(problem)
    db.commit()
