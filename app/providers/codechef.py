# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""CodeChef judge provider.

CodeChef has no official public API for a user's solved problems (the official
api.codechef.com requires per-app OAuth registration), and the redesigned public
profile only lists *contest* problems by name — practice problems are counted but
not enumerated, and no problem codes are exposed.

The reliable, complete, code-bearing public source is the "recent activity" feed
that powers the profile's submissions widget:

    GET /recent/user?page={n}&user_handle={username}

It returns ``{"max_page": N, "content": "<table>…</table>"}`` newest-first and
paginates through the user's *entire* submission history. Walking every page and
keeping the ``accepted`` rows yields the full solved list with problem codes,
first-solved dates and languages — only a public username is required.

The daily contribution calendar comes from ``userDailySubmissionsStats`` embedded
in the profile page (the same data CodeChef renders in its heatmap).
"""

from __future__ import annotations

import json
import re
import time
from datetime import date, datetime

import requests

from .base import JudgeProvider, ProblemData
from .languages import normalize_language

BASE = "https://www.codechef.com"
RECENT_URL = BASE + "/recent/user"
PROFILE_URL = BASE + "/users/{username}"
MAX_PAGES = 400  # safety cap (~4k submissions); a background job walks them all

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CODE = re.compile(r"/problems/([A-Za-z0-9_\-]+)'")
_STATUS = re.compile(r"title='([^']*)'\s*style='display: flex")
_LANG = re.compile(r"<td[^>]*title='([^']*)'>\s*([^<]*?)\s*</td>")
_DATE = re.compile(r"title='(\d{1,2}:\d{2}\s*[AP]M\s*\d{2}/\d{2}/\d{2})'")
_HEATMAP = re.compile(r"userDailySubmissionsStats\s*=\s*(\[.*?\])\s*;", re.S)


class CodeChefProvider(JudgeProvider):
    name = "codechef"
    label = "CodeChef"
    color = "#8d6748"
    syncable = True
    supports_submissions = False
    supports_activity_calendar = True
    supports_metadata = False

    def has_credentials(self, credentials: dict | None) -> bool:
        # CodeChef sync/calendar is public — only a username is needed; there is
        # no per-problem submission API to authenticate against.
        return False

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "Accept": "application/json, text/html, */*",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                "Referer": "https://www.codechef.com/",
            }
        )
        return s

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        cleaned = re.sub(r"\s+", " ", value).strip()
        try:
            return datetime.strptime(cleaned, "%I:%M %p %d/%m/%y").date()
        except ValueError:
            return None

    @classmethod
    def _accepted_rows(cls, content: str):
        """Yield (code, date, language) for each accepted submission row."""
        for row in _ROW.findall(content or ""):
            status = _STATUS.search(row)
            if not status or status.group(1).strip().lower() != "accepted":
                continue
            code = _CODE.search(row)
            if not code:
                continue
            d = _DATE.search(row)
            langs = _LANG.findall(row)
            # The only <td title='…'>plain text</td> cell is the language column.
            language = langs[-1][0] if langs else None
            yield code.group(1), cls._parse_date(d.group(1) if d else None), language

    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        username = (credentials.get("username") or "").strip()
        if not username:
            raise RuntimeError("A CodeChef username is required to sync solved problems.")

        session = self._session()
        # code -> [earliest solved date, language at that solve]
        solved: dict[str, list] = {}
        page = 0
        max_page = 0

        while page <= min(max_page, MAX_PAGES):
            resp = session.get(
                RECENT_URL, params={"page": page, "user_handle": username}, timeout=30
            )
            if resp.status_code == 404:
                raise RuntimeError(f"CodeChef user '{username}' was not found.")
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                break
            if page == 0:
                max_page = int(data.get("max_page") or 0)

            for code, solved_on, language in self._accepted_rows(data.get("content", "")):
                rec = solved.get(code)
                if rec is None:
                    solved[code] = [solved_on, normalize_language(language)]
                elif solved_on and (rec[0] is None or solved_on < rec[0]):
                    # Feed is newest-first; keep the oldest (first) accepted solve.
                    rec[0] = solved_on
                    rec[1] = normalize_language(language)

            page += 1
            if page <= min(max_page, MAX_PAGES):
                time.sleep(0.2)

        return [
            ProblemData(
                judge="CodeChef",
                external_id=None,
                slug=code,
                title=code,
                url=f"{BASE}/problems/{code}",
                date_solved=solved_on,
                language=language,
                account=username,
            )
            for code, (solved_on, language) in solved.items()
        ]

    def fetch_activity_calendar(self, credentials: dict) -> dict[str, int]:
        username = (credentials.get("username") or "").strip()
        if not username:
            raise RuntimeError("A CodeChef username is required.")
        session = self._session()
        resp = session.get(
            PROFILE_URL.format(username=username),
            headers={"Accept": "text/html"},
            timeout=30,
            allow_redirects=True,
        )
        if resp.status_code == 404:
            raise RuntimeError(f"CodeChef user '{username}' was not found.")
        resp.raise_for_status()
        m = _HEATMAP.search(resp.text)
        if not m:
            return {}
        try:
            entries = json.loads(m.group(1))
        except ValueError:
            return {}
        calendar: dict[str, int] = {}
        for e in entries:
            raw = e.get("date")
            try:
                count = int(e.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if not raw:
                continue
            # CodeChef emits non-zero-padded dates, e.g. "2025-3-9".
            parts = str(raw).split("-")
            if len(parts) != 3:
                continue
            try:
                day = date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
            except ValueError:
                continue
            calendar[day] = calendar.get(day, 0) + count
        return calendar
