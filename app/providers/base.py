# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Judge provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class ProblemData:
    """Normalized problem record returned by any judge provider."""

    judge: str
    external_id: str | None
    slug: str | None
    title: str
    url: str | None
    difficulty: str | None = None
    topics: list[str] = field(default_factory=list)
    language: str | None = None
    date_solved: date | None = None
    #: the judge account (username/handle) this problem was solved on
    account: str | None = None


@dataclass
class SubmissionData:
    """Normalized submission record."""

    external_id: str
    lang: str | None = None
    status: str | None = None
    runtime: str | None = None
    memory: str | None = None
    submitted_at: datetime | None = None
    url: str | None = None
    code: str | None = None


class JudgeProvider(ABC):
    """Adapter for an online judge.

    Implementations turn a user's credentials into a normalized list of solved
    problems. Add a new judge by subclassing this and registering it.
    """

    #: lowercase identifier, e.g. "leetcode"
    name: str = ""
    #: human-readable label
    label: str = ""
    #: brand color used for unified judge badges in the UI
    color: str = "#6366f1"

    #: whether this provider can auto-sync solved problems from the judge
    syncable: bool = True
    #: whether this provider can return per-problem submissions
    supports_submissions: bool = False
    #: whether this provider exposes an aggregate daily submission calendar
    supports_activity_calendar: bool = False
    #: whether this provider can enrich a problem's difficulty/topics by slug
    supports_metadata: bool = False

    def has_credentials(self, credentials: dict | None) -> bool:
        """Whether the given credentials are enough to fetch submissions/code."""
        return bool(credentials and (credentials.get("session_cookie") or credentials.get("leetcode_session")))

    def resolve_account(self, credentials: dict) -> str | None:
        """Resolve the account (username/handle) these credentials belong to.

        Used to attribute synced problems to a specific account so a user can
        connect multiple accounts on one judge and unsync them independently.
        The default returns the supplied username; providers that authenticate
        by cookie (e.g. LeetCode) can resolve the handle from the session.
        """
        return (credentials.get("username") or "").strip() or None

    @abstractmethod
    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        """Return all problems the user has solved on this judge."""
        raise NotImplementedError

    def fetch_activity_calendar(self, credentials: dict) -> dict[str, int]:
        """Return a {YYYY-MM-DD: submission_count} map of daily activity."""
        raise NotImplementedError(f"{self.label} has no activity calendar.")

    def fetch_problem_meta(self, slug: str) -> dict | None:
        """Return {difficulty, topics} for a problem slug, or None if unknown."""
        return None

    def fetch_submissions(self, credentials: dict, slug: str) -> list[SubmissionData]:
        """Return the user's submissions for a single problem (newest first)."""
        raise NotImplementedError(f"{self.label} does not support submissions.")

    def fetch_submission_code(self, credentials: dict, submission_id: str) -> SubmissionData:
        """Return code + metadata for a single submission."""
        raise NotImplementedError(f"{self.label} does not support submission code.")
