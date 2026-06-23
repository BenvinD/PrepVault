# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Spaced-repetition scheduling + a smart, weakness-aware revision queue.

Scheduling mirrors the original spreadsheet logic: the next review date is the
last practice date plus an interval that grows with confidence.

On top of that, `build_revision_queue` turns the flat "due" list into a
prioritized queue. Rather than dumping everything at once, the UI works through
it a few problems at a time, hardest-first. Priority blends:

  - how overdue the problem is (spaced repetition: revise what you're about to
    forget),
  - how weak the user is in the problem's topics (interview-prep focus),
  - low/absent confidence,
  - an explicit "revisit" flag,
  - a small nudge toward harder problems.

Topic weakness is derived from the user's own data (average confidence, the
share of due problems, and revisit flags per topic), so the queue adapts to
where they actually struggle.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .presentation import split_topics, unify_problem

# confidence (1-5) -> days until next revision
INTERVALS = {1: 2, 2: 4, 3: 7, 4: 14, 5: 30}
DEFAULT_INTERVAL = 7

# Priority weights (sum to 1.0). Tunable; surfaced here for easy tweaking.
_W_OVERDUE = 0.35
_W_TOPIC = 0.30
_W_CONFIDENCE = 0.20
_W_REVISIT = 0.10
_W_DIFFICULTY = 0.05

_DIFF_FACTOR = {"easy": 0.3, "medium": 0.6, "hard": 1.0}
_OVERDUE_CAP_DAYS = 30
# A topic at/above this weakness is called out as a "weak topic".
_WEAK_TOPIC_THRESHOLD = 0.55
# Default weakness for a topic we have no signal on (leans slightly weak).
_UNKNOWN_TOPIC_WEAKNESS = 0.4


def next_revision_date(
    base: date | None, confidence: int | None
) -> date | None:
    if base is None:
        return None
    interval = INTERVALS.get(confidence or 0, DEFAULT_INTERVAL)
    return base + timedelta(days=interval)


def compute_next_revision(problem) -> date | None:
    """Pick the anchor date (last_revised preferred, else date_solved)."""
    anchor = problem.last_revised or problem.date_solved
    return next_revision_date(anchor, problem.confidence)


def _confidence_factor(confidence: int | None) -> float:
    """0.2 (mastered, conf 5) .. 1.0 (struggling, conf 1); 0.8 when unset."""
    if not confidence:
        return 0.8
    return max(0.0, min(1.0, (6 - confidence) / 5))


def topic_weakness(db: Session, user_id: int, today: date | None = None) -> dict[str, dict]:
    """Per-topic weakness derived from the user's own problems.

    weakness (0..1) = 0.6 * low-confidence + 0.25 * due-share + 0.15 * revisit-share
    """
    from ..models import Problem

    today = today or date.today()
    problems = db.execute(
        select(Problem).where(Problem.user_id == user_id)
    ).scalars().all()

    agg: dict[str, dict] = {}
    for p in problems:
        for topic in split_topics(p.topics):
            s = agg.setdefault(
                topic, {"count": 0, "conf_sum": 0, "conf_n": 0, "due": 0, "revisit": 0}
            )
            s["count"] += 1
            if p.confidence:
                s["conf_sum"] += p.confidence
                s["conf_n"] += 1
            if p.next_revision and p.next_revision <= today:
                s["due"] += 1
            if p.revisit:
                s["revisit"] += 1

    out: dict[str, dict] = {}
    for topic, s in agg.items():
        avg_conf = (s["conf_sum"] / s["conf_n"]) if s["conf_n"] else None
        weakness_conf = (6 - avg_conf) / 5 if avg_conf is not None else 0.6
        due_ratio = s["due"] / s["count"] if s["count"] else 0.0
        revisit_ratio = s["revisit"] / s["count"] if s["count"] else 0.0
        weakness = 0.6 * weakness_conf + 0.25 * due_ratio + 0.15 * revisit_ratio
        out[topic] = {
            "weakness": round(min(1.0, max(0.0, weakness)), 3),
            "count": s["count"],
            "due": s["due"],
            "avg_confidence": round(avg_conf, 2) if avg_conf is not None else None,
        }
    return out


def build_revision_queue(db: Session, user_id: int, batch_size: int = 5) -> dict:
    """Return due problems in smart priority order, plus weak-topic context."""
    from ..models import Problem

    today = date.today()
    weakness = topic_weakness(db, user_id, today)

    due = db.execute(
        select(Problem).where(
            Problem.user_id == user_id,
            Problem.next_revision.is_not(None),
            Problem.next_revision <= today,
        )
    ).scalars().all()

    items: list[dict] = []
    for p in due:
        topics = split_topics(p.topics)
        overdue_days = max(0, (today - p.next_revision).days) if p.next_revision else 0
        f_overdue = min(overdue_days / _OVERDUE_CAP_DAYS, 1.0)
        f_conf = _confidence_factor(p.confidence)
        topic_pairs = [(t, weakness.get(t, {}).get("weakness", _UNKNOWN_TOPIC_WEAKNESS)) for t in topics]
        f_topic = max((w for _, w in topic_pairs), default=_UNKNOWN_TOPIC_WEAKNESS)
        f_revisit = 1.0 if p.revisit else 0.0
        f_diff = _DIFF_FACTOR.get((p.difficulty or "").lower(), 0.5)

        score = (
            _W_OVERDUE * f_overdue
            + _W_TOPIC * f_topic
            + _W_CONFIDENCE * f_conf
            + _W_REVISIT * f_revisit
            + _W_DIFFICULTY * f_diff
        )

        weak_matched = sorted(
            (t for t, w in topic_pairs if w >= _WEAK_TOPIC_THRESHOLD),
            key=lambda t: weakness.get(t, {}).get("weakness", 0),
            reverse=True,
        )[:2]

        reasons: list[str] = []
        if overdue_days > 0:
            reasons.append(f"Overdue {overdue_days}d")
        else:
            reasons.append("Due today")
        if weak_matched:
            reasons.append("Weak topic: " + ", ".join(weak_matched))
        if p.confidence and p.confidence <= 2:
            reasons.append("Low confidence")
        elif not p.confidence:
            reasons.append("No confidence set")
        if p.revisit:
            reasons.append("Flagged to revisit")

        item = unify_problem(p)
        item["priority"] = round(score, 4)
        item["reasons"] = reasons
        item["weak_topics_matched"] = weak_matched
        items.append(item)

    items.sort(key=lambda it: it["priority"], reverse=True)

    weak_topics = sorted(
        ({"topic": t, **v} for t, v in weakness.items() if v["due"] > 0),
        key=lambda d: d["weakness"],
        reverse=True,
    )[:6]

    return {
        "total_due": len(items),
        "batch_size": batch_size,
        "weak_topics": weak_topics,
        "items": items,
    }
