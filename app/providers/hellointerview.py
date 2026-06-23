# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""HelloInterview judge provider (manual tracking).

HelloInterview (hellointerview.com) runs a private internal tRPC API and does
not expose a public endpoint for fetching a user's coding progress. There is
therefore no way to auto-sync solved problems. This provider exists so the
platform is recognized throughout the app; problems and their code are tracked
by adding them manually (with the code you wrote) through the UI/API.
"""

from __future__ import annotations

from .base import JudgeProvider, ProblemData


class HelloInterviewProvider(JudgeProvider):
    name = "hellointerview"
    label = "HelloInterview"
    color = "#8b5cf6"
    syncable = False  # no public API
    supports_submissions = False  # manual code tracking only

    def fetch_solved(self, credentials: dict) -> list[ProblemData]:
        raise RuntimeError(
            "HelloInterview has no public API to sync from. Add HelloInterview "
            "problems manually and paste your code to track them."
        )
