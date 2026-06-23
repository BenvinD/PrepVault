# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""SQLAlchemy models.

Kept deliberately close to the original tracker spreadsheet so the data is
familiar, while adding per-user ownership for multi-tenant cloud use.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_local: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    problems: Mapped[list["Problem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Problem(Base):
    __tablename__ = "problems"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "judge", "account", "slug", name="uq_user_judge_account_slug"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    judge: Mapped[str] = mapped_column(String(40), default="LeetCode")
    # The judge account (username/handle) this problem was synced from. Lets a
    # user connect multiple accounts on the same judge and unsync one cleanly.
    # NULL for manually-added problems or legacy rows not yet attributed.
    account: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    topics: Mapped[str | None] = mapped_column(String(500), nullable=True)
    languages: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="solved")
    date_solved: Mapped[date | None] = mapped_column(Date, nullable=True)
    first_solved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_revised: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_revision: Mapped[date | None] = mapped_column(Date, nullable=True)
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revisit: Mapped[bool] = mapped_column(Boolean, default=False)
    approach: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(20), default="sync")  # sync | manual
    submissions_fetched: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship(back_populates="problems")
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="problem", cascade="all, delete-orphan"
    )


class Submission(Base):
    """A single submission for a problem (most recent / accepted history)."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("problem_id", "external_id", name="uq_problem_submission"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id", ondelete="CASCADE"), index=True)

    external_id: Mapped[str] = mapped_column(String(40))
    lang: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    runtime: Mapped[str | None] = mapped_column(String(40), nullable=True)
    memory: Mapped[str | None] = mapped_column(String(40), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    code: Mapped[str | None] = mapped_column(Text, nullable=True)

    problem: Mapped["Problem"] = relationship(back_populates="submissions")


class ActivityDay(Base):
    """Per-day, per-judge submission counts for the activity graph.

    Some judges (e.g. HackerRank) expose an aggregate daily submission calendar
    but no per-problem submission API. We store that calendar here so the
    contribution graph reflects real historical activity for those providers.
    """

    __tablename__ = "activity_days"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "judge", "account", "day", name="uq_user_judge_account_day"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    judge: Mapped[str] = mapped_column(String(40))
    account: Mapped[str | None] = mapped_column(String(120), nullable=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Job(Base):
    """A unit of background work (sync, backfill, insight, future embeddings).

    Slow/external work is enqueued instead of running inline in a request. The
    handler returns a job id; the client polls `GET /api/jobs/{id}`. When no
    worker is configured (local mode), the dispatcher runs the task inline and
    the job is already terminal when returned — so the same contract serves
    both modes with zero config. Secrets are NEVER stored on the job; tasks
    decrypt credentials from the vault at fetch time.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    # queued | running | success | error
    status: Mapped[str] = mapped_column(String(20), default="queued")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class JudgeCredential(Base):
    """Per-user judge credentials, used to fetch submissions on demand.

    Secret fields (session cookie, csrf token) are passed through the secrets
    vault (`app/security/vault.py`) before storage. Local-first runs use the
    passthrough backend; hosted deployments set VAULT_BACKEND=fernet so secrets
    are encrypted at rest. Plaintext secrets are never logged.
    """

    __tablename__ = "judge_credentials"
    __table_args__ = (
        # One row per (user, judge, account) so multiple accounts on the same
        # judge can each keep their own cookie/handle.
        UniqueConstraint("user_id", "judge", "username", name="uq_user_judge_username_cred"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    judge: Mapped[str] = mapped_column(String(40))
    session_cookie: Mapped[str | None] = mapped_column(Text, nullable=True)
    csrftoken: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
