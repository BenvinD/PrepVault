# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class ConfigOut(BaseModel):
    app_name: str
    mode: str
    auth_required: bool
    llm_enabled: bool
    features: dict[str, bool] = {}


class Credentials(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProblemBase(BaseModel):
    judge: str = "LeetCode"
    external_id: str | None = None
    slug: str | None = None
    title: str
    url: str | None = None
    difficulty: str | None = None
    topics: str | None = None
    languages: str | None = None
    status: str = "solved"
    date_solved: date | None = None
    confidence: int | None = None
    revisit: bool = False
    approach: str | None = None


class ProblemCreate(ProblemBase):
    pass


class ProblemUpdate(BaseModel):
    confidence: int | None = None
    revisit: bool | None = None
    approach: str | None = None
    last_revised: date | None = None
    difficulty: str | None = None
    topics: str | None = None
    languages: str | None = None


class ProblemOut(ProblemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_solved_at: datetime | None = None
    last_revised: date | None = None
    next_revision: date | None = None
    source: str
    submissions_fetched: bool = False


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    lang: str | None = None
    status: str | None = None
    runtime: str | None = None
    memory: str | None = None
    submitted_at: datetime | None = None
    url: str | None = None
    has_code: bool = False


class SubmissionCodeOut(BaseModel):
    id: int
    external_id: str
    lang: str | None = None
    code: str | None = None


class ManualSubmissionIn(BaseModel):
    code: str | None = None
    lang: str | None = None
    status: str = "Accepted"
    runtime: str | None = None
    memory: str | None = None
    submitted_at: datetime | None = None


class ProviderOut(BaseModel):
    name: str
    label: str
    color: str = "#6366f1"
    syncable: bool
    supports_submissions: bool


class SyncRequest(BaseModel):
    judge: str = "leetcode"
    # LeetCode auth: session cookie (full solved list). Username alone only
    # exposes recent submissions on the public API.
    leetcode_session: str | None = None
    # Generic judge session cookie (e.g. HackerRank `_hrank_session`).
    session_cookie: str | None = None
    csrftoken: str | None = None
    username: str | None = None


class UnsyncRequest(BaseModel):
    judge: str
    account: str | None = None


class SyncResult(BaseModel):
    fetched: int
    added: int
    skipped: int
    judge: str
    message: str


class JobOut(BaseModel):
    """Envelope returned by enqueue endpoints and GET /api/jobs/{id}.

    In local (inline) mode the job is already terminal (`success`/`error`) with
    its `result` populated; in worker mode it starts `queued` and the client
    polls until terminal.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    status: str
    result: dict | None = None
    error: str | None = None


class ImportResult(BaseModel):
    problems_added: int
    problems_merged: int
    submissions_added: int
    activity_days_added: int
    message: str


class StatsOut(BaseModel):
    total: int
    by_difficulty: dict[str, int]
    by_status: dict[str, int]
    top_topics: list[tuple[str, int]]
    due_for_revision: int
    solved_last_30_days: int
