# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Judge providers.

Each online judge is a pluggable adapter implementing the `JudgeProvider`
interface. Register new judges in `REGISTRY` and the rest of the app (sync
service, API, UI) works with them without changes.
"""

from __future__ import annotations

from .base import JudgeProvider, ProblemData
from .codechef import CodeChefProvider
from .hackerrank import HackerRankProvider
from .hellointerview import HelloInterviewProvider
from .leetcode import LeetCodeProvider

REGISTRY: dict[str, type[JudgeProvider]] = {
    LeetCodeProvider.name: LeetCodeProvider,
    HackerRankProvider.name: HackerRankProvider,
    CodeChefProvider.name: CodeChefProvider,
    HelloInterviewProvider.name: HelloInterviewProvider,
}


def get_provider(name: str) -> JudgeProvider:
    key = name.lower().strip()
    if key not in REGISTRY:
        raise KeyError(f"Unknown judge provider '{name}'. Available: {list(REGISTRY)}")
    return REGISTRY[key]()


__all__ = ["JudgeProvider", "ProblemData", "REGISTRY", "get_provider"]
