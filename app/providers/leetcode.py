# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""LeetCode judge provider.

Uses LeetCode's authenticated GraphQL API. A LEETCODE_SESSION cookie yields the
full solved list (the data behind leetcode.com/progress); a bare username only
exposes recent accepted submissions via the public API.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from .base import JudgeProvider, ProblemData, SubmissionData
from .languages import normalize_language

GRAPHQL_URL = "https://leetcode.com/graphql"

TOPIC_MAP = {
    "Hash Table": "Hash Map",
    "Depth-First Search": "DFS",
    "Breadth-First Search": "BFS",
    "Prefix Sum": "Pre Fix Sum",
    "Heap (Priority Queue)": "Heap",
}

SOLVED_QUERY = """
query problemsetQuestionList($categorySlug: String, $limit: Int, $skip: Int, $filters: QuestionListFilterInput) {
  problemsetQuestionList: questionList(categorySlug: $categorySlug, limit: $limit, skip: $skip, filters: $filters) {
    total: totalNum
    questions: data {
      frontendId: questionFrontendId
      title
      titleSlug
      difficulty
      status
      topicTags { name }
    }
  }
}
"""

RECENT_AC_QUERY = """
query recentAcSubmissions($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    titleSlug
    timestamp
    lang
  }
}
"""

WHOAMI_QUERY = "query globalData { userStatus { username isSignedIn } }"

SUBMISSIONS_QUERY = """
query submissionList($offset: Int!, $limit: Int!, $lastKey: String, $questionSlug: String!) {
  questionSubmissionList(offset: $offset, limit: $limit, lastKey: $lastKey, questionSlug: $questionSlug) {
    lastKey
    hasNext
    submissions {
      id
      statusDisplay
      lang
      langName
      runtime
      memory
      timestamp
      url
    }
  }
}
"""

SUBMISSION_DETAIL_QUERY = """
query submissionDetails($submissionId: Int!) {
  submissionDetails(submissionId: $submissionId) {
    code
    runtime
    memory
    timestamp
    statusCode
    lang { name verboseName }
  }
}
"""


class LeetCodeProvider(JudgeProvider):
    name = "leetcode"
    label = "LeetCode"
    color = "#ffa116"
    supports_submissions = True

    def _session(self, credentials: dict) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Referer": "https://leetcode.com/problemset/all/",
                "Origin": "https://leetcode.com",
            }
        )
        session_cookie = credentials.get("leetcode_session")
        csrf = credentials.get("csrftoken") or ""
        if session_cookie:
            cookie = f"LEETCODE_SESSION={session_cookie};"
            if csrf:
                cookie += f" csrftoken={csrf};"
                s.headers["x-csrftoken"] = csrf
            s.headers["Cookie"] = cookie
        return s

    def resolve_account(self, credentials: dict) -> str | None:
        u = (credentials.get("username") or "").strip()
        if u:
            return u
        if credentials.get("leetcode_session"):
            try:
                data = self._gql(self._session(credentials), WHOAMI_QUERY, {})
            except RuntimeError:
                return None
            return (data.get("userStatus") or {}).get("username") or None
        return None

    def _gql(self, session: requests.Session, query: str, variables: dict) -> dict:
        resp = session.post(GRAPHQL_URL, json={"query": query, "variables": variables}, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"LeetCode GraphQL error: {payload['errors']}")
        return payload["data"]

    def _recent_meta(self, session: requests.Session, username: str) -> dict:
        meta: dict[str, tuple] = {}
        try:
            data = self._gql(session, RECENT_AC_QUERY, {"username": username, "limit": 1000})
        except RuntimeError:
            return meta
        for sub in data.get("recentAcSubmissionList") or []:
            slug = sub["titleSlug"]
            if slug in meta:
                continue
            solved_on = datetime.fromtimestamp(int(sub["timestamp"]), tz=timezone.utc).date()
            lang = normalize_language(sub.get("lang"))
            meta[slug] = (solved_on, lang)
        return meta

    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        session = self._session(credentials)
        username = credentials.get("username")

        signed_in = False
        if credentials.get("leetcode_session"):
            data = self._gql(session, WHOAMI_QUERY, {})
            status = data.get("userStatus") or {}
            signed_in = bool(status.get("isSignedIn"))
            username = username or status.get("username")

        if not signed_in:
            # Public fallback: recent accepted submissions only.
            if not username:
                raise RuntimeError(
                    "Provide a valid LEETCODE_SESSION cookie (for your full solved "
                    "list) or at least a username (recent submissions only)."
                )
            meta = self._recent_meta(session, username)
            return [
                ProblemData(
                    judge="LeetCode",
                    external_id=None,
                    slug=slug,
                    title=slug.replace("-", " ").title(),
                    url=f"https://leetcode.com/problems/{slug}/",
                    date_solved=solved_on,
                    language=lang,
                    account=username,
                )
                for slug, (solved_on, lang) in meta.items()
            ]

        # Authenticated: full solved catalog with topics + difficulty.
        recent_meta = self._recent_meta(session, username) if username else {}
        solved: list[ProblemData] = []
        skip, limit = 0, 100
        while True:
            data = self._gql(
                session,
                SOLVED_QUERY,
                {"categorySlug": "", "skip": skip, "limit": limit, "filters": {"status": "AC"}},
            )
            block = data["problemsetQuestionList"]
            for q in block["questions"]:
                if q.get("status") != "ac":
                    continue
                slug = q["titleSlug"]
                solved_on, lang = recent_meta.get(slug, (None, None))
                topics = [TOPIC_MAP.get(t["name"], t["name"]) for t in (q.get("topicTags") or [])]
                solved.append(
                    ProblemData(
                        judge="LeetCode",
                        external_id=str(q["frontendId"]),
                        slug=slug,
                        title=q["title"],
                        url=f"https://leetcode.com/problems/{slug}/",
                        difficulty=q.get("difficulty"),
                        topics=topics,
                        language=lang,
                        date_solved=solved_on,
                        account=username,
                    )
                )
            skip += limit
            if skip >= block["total"] or not block["questions"]:
                break
            time.sleep(0.4)
        return solved

    def fetch_submissions(self, credentials: dict, slug: str) -> list[SubmissionData]:
        if not credentials.get("leetcode_session"):
            raise RuntimeError("A LEETCODE_SESSION cookie is required to view submissions.")
        session = self._session(credentials)
        results: list[SubmissionData] = []
        offset, limit, last_key = 0, 20, None
        while True:
            data = self._gql(
                session,
                SUBMISSIONS_QUERY,
                {"offset": offset, "limit": limit, "lastKey": last_key, "questionSlug": slug},
            )
            block = data.get("questionSubmissionList") or {}
            for s in block.get("submissions") or []:
                ts = s.get("timestamp")
                submitted_at = (
                    datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
                )
                results.append(
                    SubmissionData(
                        external_id=str(s["id"]),
                        lang=normalize_language(s.get("langName") or s.get("lang")),
                        status=s.get("statusDisplay"),
                        runtime=s.get("runtime"),
                        memory=s.get("memory"),
                        submitted_at=submitted_at,
                        url=("https://leetcode.com" + s["url"]) if s.get("url") else None,
                    )
                )
            if not block.get("hasNext"):
                break
            last_key = block.get("lastKey")
            offset += limit
            time.sleep(0.3)
        return results

    def fetch_submission_code(self, credentials: dict, submission_id: str) -> SubmissionData:
        if not credentials.get("leetcode_session"):
            raise RuntimeError("A LEETCODE_SESSION cookie is required to view code.")
        session = self._session(credentials)
        data = self._gql(session, SUBMISSION_DETAIL_QUERY, {"submissionId": int(submission_id)})
        detail = data.get("submissionDetails") or {}
        ts = detail.get("timestamp")
        lang = detail.get("lang") or {}
        return SubmissionData(
            external_id=str(submission_id),
            lang=normalize_language(lang.get("verboseName") or lang.get("name")),
            runtime=detail.get("runtime"),
            memory=detail.get("memory"),
            submitted_at=(datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None),
            code=detail.get("code"),
        )
