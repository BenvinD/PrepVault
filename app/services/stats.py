# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Dashboard aggregates."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Problem
from ..schemas import StatsOut
from .presentation import difficulty_meta


def compute_stats(db: Session, user_id: int) -> StatsOut:
    problems = db.execute(select(Problem).where(Problem.user_id == user_id)).scalars().all()
    today = date.today()
    cutoff = today - timedelta(days=30)

    by_difficulty: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    topic_counter: Counter[str] = Counter()
    due = 0
    last_30 = 0

    for p in problems:
        by_difficulty[difficulty_meta(p.difficulty)["label"] or "Unknown"] += 1
        by_status[p.status or "unknown"] += 1
        if p.topics:
            for t in p.topics.split(","):
                t = t.strip()
                if t:
                    topic_counter[t] += 1
        if p.next_revision and p.next_revision <= today:
            due += 1
        if p.date_solved and p.date_solved >= cutoff:
            last_30 += 1

    return StatsOut(
        total=len(problems),
        by_difficulty=dict(by_difficulty),
        by_status=dict(by_status),
        top_topics=topic_counter.most_common(10),
        due_for_revision=due,
        solved_last_30_days=last_30,
    )
