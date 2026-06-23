# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Combined activity analytics across all judges.

Builds a GitHub-style contribution calendar plus a bundle of insights from the
user's solve/submission history. An "event" is one accepted-submission day for
a problem, or — if a problem has no dated submissions — its first-solved day.
This keeps the calendar stable (submissions are only fetched on demand) while
getting richer automatically as submission history is backfilled.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ActivityDay, Problem, Submission
from .presentation import difficulty_meta, provider_meta

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def store_calendar(
    db: Session,
    user_id: int,
    judge: str,
    calendar: dict[str, int],
    account: str | None = None,
) -> int:
    """Upsert an aggregate daily-submission calendar for a judge account."""
    existing = {
        row.day: row
        for row in db.execute(
            select(ActivityDay).where(
                ActivityDay.user_id == user_id,
                ActivityDay.judge == judge,
                ActivityDay.account == account,
            )
        ).scalars()
    }
    stored = 0
    for day_str, count in calendar.items():
        try:
            day = date.fromisoformat(day_str)
        except ValueError:
            continue
        count = int(count or 0)
        if day in existing:
            existing[day].count = count
        else:
            db.add(
                ActivityDay(
                    user_id=user_id, judge=judge, account=account, day=day, count=count
                )
            )
        stored += 1
    db.commit()
    return stored


def _events(db: Session, user_id: int) -> list[dict]:
    problems = db.execute(select(Problem).where(Problem.user_id == user_id)).scalars().all()
    subs = db.execute(select(Submission).where(Submission.user_id == user_id)).scalars().all()

    subs_by_problem: dict[int, list[Submission]] = defaultdict(list)
    for s in subs:
        if s.submitted_at:
            subs_by_problem[s.problem_id].append(s)

    events: list[dict] = []
    for p in problems:
        dated = subs_by_problem.get(p.id, [])
        if dated:
            for s in dated:
                events.append(
                    {
                        "date": s.submitted_at.date(),
                        "judge": p.judge,
                        "difficulty": p.difficulty,
                        "title": p.title,
                        "topics": p.topics,
                        "kind": "submission",
                    }
                )
        else:
            d = p.date_solved or (p.first_solved_at.date() if p.first_solved_at else None)
            if d:
                events.append(
                    {
                        "date": d,
                        "judge": p.judge,
                        "difficulty": p.difficulty,
                        "title": p.title,
                        "topics": p.topics,
                        "kind": "solve",
                    }
                )
    return events


def _streaks(active_days: set[date]) -> tuple[int, int]:
    if not active_days:
        return 0, 0
    longest = 0
    for d in active_days:
        if (d - timedelta(days=1)) in active_days:
            continue  # not a run start
        run, cur = 1, d
        while (cur + timedelta(days=1)) in active_days:
            cur += timedelta(days=1)
            run += 1
        longest = max(longest, run)

    today = date.today()
    anchor = today if today in active_days else today - timedelta(days=1)
    current = 0
    cur = anchor
    while cur in active_days:
        current += 1
        cur -= timedelta(days=1)
    return current, longest


def _stored_calendars(db: Session, user_id: int) -> dict[str, dict[date, int]]:
    cals: dict[str, dict[date, int]] = defaultdict(dict)
    for row in db.execute(
        select(ActivityDay).where(ActivityDay.user_id == user_id)
    ).scalars():
        cals[row.judge][row.day] = cals[row.judge].get(row.day, 0) + row.count
    return cals


def compute_activity(db: Session, user_id: int, year: int | None = None) -> dict:
    events = _events(db, user_id)
    calendars = _stored_calendars(db, user_id)
    cal_judges = set(calendars)

    # Daily totals across all years (for streaks + available years). Judges that
    # have a stored calendar contribute via the calendar; others via solve events.
    global_day: Counter[date] = Counter()
    for e in events:
        if e["judge"] not in cal_judges:
            global_day[e["date"]] += 1
    for days in calendars.values():
        for d, c in days.items():
            global_day[d] += c
    active_days_all = {d for d, c in global_day.items() if c > 0}
    current_streak, longest_streak = _streaks(active_days_all)

    years = sorted({d.year for d in active_days_all})
    if year is None:
        year = years[-1] if years else date.today().year

    year_events = [e for e in events if e["date"].year == year]

    per_day: Counter[date] = Counter()
    weekday: Counter[int] = Counter()
    month: Counter[int] = Counter()
    provider: Counter[str] = Counter()
    difficulty: Counter[str] = Counter()
    topics: Counter[str] = Counter()
    day_items: dict[str, list[dict]] = defaultdict(list)
    seen_day_problem: set[tuple[str, str]] = set()

    # Per-day contribution counts: calendar judges use the calendar; others count
    # solve/submission events. Qualitative detail (difficulty/topics/day items)
    # always comes from per-problem events.
    for e in year_events:
        d = e["date"]
        if e["judge"] not in cal_judges:
            per_day[d] += 1
            provider[e["judge"]] += 1
        difficulty[difficulty_meta(e["difficulty"])["label"] or "Unknown"] += 1
        key = (d.isoformat(), e["title"])
        if key not in seen_day_problem:
            seen_day_problem.add(key)
            day_items[d.isoformat()].append(
                {
                    "title": e["title"],
                    "judge": provider_meta(e["judge"]),
                    "difficulty": difficulty_meta(e["difficulty"]),
                }
            )
        if e["topics"]:
            for t in e["topics"].split(","):
                t = t.strip()
                if t:
                    topics[t] += 1

    for judge, days in calendars.items():
        total = 0
        for d, c in days.items():
            if d.year == year:
                per_day[d] += c
                total += c
        if total:
            provider[judge] += total

    for d, c in per_day.items():
        weekday[d.weekday()] += c
        month[d.month] += c

    # Full calendar for the year (every day, including zeros).
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    calendar = []
    d = start
    while d <= end:
        calendar.append({"date": d.isoformat(), "count": per_day.get(d, 0)})
        d += timedelta(days=1)

    max_day = max(per_day.items(), key=lambda kv: kv[1], default=None)

    return {
        "year": year,
        "years_available": years,
        "calendar": calendar,
        "total_events": sum(per_day.values()),
        "active_days": len([1 for c in per_day.values() if c > 0]),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "busiest_day": (
            {"date": max_day[0].isoformat(), "count": max_day[1]} if max_day else None
        ),
        "by_weekday": [{"label": WEEKDAYS[i], "count": weekday.get(i, 0)} for i in range(7)],
        "by_month": [
            {"month": m, "count": month.get(m, 0)}
            for m in range(1, 13)
        ],
        "by_provider": [
            {"judge": provider_meta(k)["label"], "color": provider_meta(k)["color"], "count": v}
            for k, v in provider.most_common()
        ],
        "by_difficulty": dict(difficulty),
        "top_topics": topics.most_common(12),
        "day_items": day_items,
    }
