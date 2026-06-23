# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Job lifecycle helpers shared by the dispatcher, tasks, and the API.

A `Job` row tracks status + result for a unit of background work. These helpers
are deliberately transport-agnostic: the same `mark_*` functions are used
whether the task runs inline (local) or inside an Arq worker (cloud).
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from ..models import Job, User


def new_job(db: Session, user: User, kind: str) -> Job:
    job = Job(id=uuid.uuid4().hex, user_id=user.id, kind=kind, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, user_id: int, job_id: str) -> Job | None:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user_id:
        return None
    return job


def mark_running(db: Session, job_id: str) -> None:
    job = db.get(Job, job_id)
    if job:
        job.status = "running"
        db.commit()


def mark_success(db: Session, job_id: str, result: dict | None) -> None:
    job = db.get(Job, job_id)
    if job:
        job.status = "success"
        job.result = json.dumps(result) if result is not None else None
        job.error = None
        db.commit()


def mark_error(db: Session, job_id: str, message: str) -> None:
    job = db.get(Job, job_id)
    if job:
        job.status = "error"
        job.error = message
        db.commit()


def result_dict(job: Job) -> dict | None:
    if not job.result:
        return None
    try:
        return json.loads(job.result)
    except (ValueError, TypeError):
        return None
