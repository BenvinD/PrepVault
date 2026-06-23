# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""HackerRank judge provider.

HackerRank has no official public API for a user's solved problems, but the
website is backed by an unauthenticated REST endpoint that powers the public
profile's "recent challenges" feed:

    GET /rest/hackers/{username}/recent_challenges?limit=20&response_version=v2

It returns solved challenges newest-first and is cursor-paginated, so walking
every page yields the user's full solved list. Only a public username is
required. Difficulty/topics are not exposed by this endpoint, so they are left
empty (they can be filled in later via the AI insight / manual edit flow).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from .base import JudgeProvider, ProblemData, SubmissionData
from .languages import normalize_language

BASE = "https://www.hackerrank.com"
RECENT_CHALLENGES_URL = BASE + "/rest/hackers/{username}/recent_challenges"
SUBMISSION_HISTORY_URL = BASE + "/rest/hackers/{username}/submission_histories"
CHALLENGE_SUBMISSIONS_URL = BASE + "/rest/contests/master/challenges/{slug}/submissions/"
SUBMISSION_DETAIL_URL = BASE + "/rest/contests/master/submissions/{sid}"
CHALLENGE_DETAIL_URL = BASE + "/rest/contests/master/challenges/{slug}"
MAX_PAGES = 500  # safety cap (~10k solved challenges)


class HackerRankProvider(JudgeProvider):
    name = "hackerrank"
    label = "HackerRank"
    color = "#1ba94c"
    syncable = True
    supports_submissions = True  # authenticated _hrank_session cookie required
    supports_activity_calendar = True  # aggregate daily submission calendar
    supports_metadata = True  # difficulty + track exposed per challenge

    def has_credentials(self, credentials: dict | None) -> bool:
        return bool(credentials and credentials.get("session_cookie"))

    def _session(self, credentials: dict | None = None) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Referer": "https://www.hackerrank.com/",
            }
        )
        token = (credentials or {}).get("session_cookie")
        if token:
            s.headers["Cookie"] = f"_hrank_session={token}"
            csrf = (credentials or {}).get("csrftoken")
            if csrf:
                s.headers["X-Csrf-Token"] = csrf
        return s

    @staticmethod
    def _parse_date(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        username = (credentials.get("username") or "").strip()
        if not username:
            raise RuntimeError("A HackerRank username is required to sync solved problems.")

        session = self._session()
        url = RECENT_CHALLENGES_URL.format(username=username)
        solved: list[ProblemData] = []
        seen: set[str] = set()
        cursor: str | None = None

        for _ in range(MAX_PAGES):
            params = {"limit": 20, "response_version": "v2"}
            if cursor:
                params["cursor"] = cursor
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 404:
                raise RuntimeError(f"HackerRank user '{username}' was not found.")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models") or []
            for m in models:
                slug = m.get("ch_slug") or m.get("slug")
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                rel = m.get("url") or f"/challenges/{slug}"
                solved.append(
                    ProblemData(
                        judge="HackerRank",
                        external_id=None,
                        slug=slug,
                        title=m.get("name") or slug.replace("-", " ").title(),
                        url=BASE + rel if rel.startswith("/") else rel,
                        date_solved=self._parse_date(m.get("created_at")),
                        account=username,
                    )
                )
            cursor = data.get("cursor")
            if data.get("last_page") or not models or not cursor:
                break
            time.sleep(0.3)

        return solved

    def fetch_activity_calendar(self, credentials: dict) -> dict[str, int]:
        username = (credentials.get("username") or "").strip()
        if not username:
            raise RuntimeError("A HackerRank username is required.")
        session = self._session()
        resp = session.get(SUBMISSION_HISTORY_URL.format(username=username), timeout=30)
        if resp.status_code == 404:
            raise RuntimeError(f"HackerRank user '{username}' was not found.")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return {}
        calendar: dict[str, int] = {}
        for day, count in data.items():
            try:
                n = int(count)
            except (TypeError, ValueError):
                continue
            # Endpoint returns ISO date strings (older variants used unix epochs).
            if str(day).isdigit():
                day = datetime.fromtimestamp(int(day), tz=timezone.utc).date().isoformat()
            calendar[str(day)] = n
        return calendar

    def fetch_problem_meta(self, slug: str) -> dict | None:
        if not slug:
            return None
        session = self._session()
        resp = session.get(CHALLENGE_DETAIL_URL.format(slug=slug), timeout=30)
        if resp.status_code != 200:
            return None
        model = (resp.json() or {}).get("model") or {}
        difficulty = model.get("difficulty_name")
        topics: list[str] = []
        track = model.get("track") or {}
        if isinstance(track, dict):
            for key in ("name", "track_name"):
                val = track.get(key)
                if val and val not in topics:
                    topics.append(val)
        return {"difficulty": difficulty, "topics": topics}

    @staticmethod
    def _to_datetime(value):
        if value is None:
            return None
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def fetch_submissions(self, credentials: dict, slug: str) -> list[SubmissionData]:
        if not self.has_credentials(credentials):
            raise RuntimeError("A HackerRank `_hrank_session` cookie is required to view submissions.")
        session = self._session(credentials)
        url = CHALLENGE_SUBMISSIONS_URL.format(slug=slug)
        results: list[SubmissionData] = []
        offset, limit = 0, 50
        while True:
            resp = session.get(url, params={"offset": offset, "limit": limit}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models") or []
            for m in models:
                sid = str(m.get("id"))
                results.append(
                    SubmissionData(
                        external_id=sid,
                        lang=normalize_language(m.get("language")),
                        status=m.get("status"),
                        runtime=None,
                        memory=None,
                        submitted_at=self._to_datetime(m.get("created_at")),
                        url=f"{BASE}/challenges/{slug}/submissions/code/{sid}",
                    )
                )
            offset += limit
            if offset >= (data.get("total") or 0) or not models:
                break
            time.sleep(0.3)
        return results

    def fetch_submission_code(self, credentials: dict, submission_id: str) -> SubmissionData:
        if not self.has_credentials(credentials):
            raise RuntimeError("A HackerRank `_hrank_session` cookie is required to view code.")
        session = self._session(credentials)
        resp = session.get(SUBMISSION_DETAIL_URL.format(sid=submission_id), timeout=30)
        resp.raise_for_status()
        model = (resp.json() or {}).get("model") or {}
        return SubmissionData(
            external_id=str(submission_id),
            lang=normalize_language(model.get("language")),
            status=model.get("status"),
            submitted_at=self._to_datetime(model.get("created_at")),
            code=model.get("code"),
        )
