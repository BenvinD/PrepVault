# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Portable export / import of a user's tracker data.

Local-first means your data lives on your machine — this lets you move it
between machines (or back it up) as a single JSON file. Import is **merge,
not replace**, and de-duplicates so re-importing the same file (or importing
overlapping data from two machines) never creates duplicates:

  - Problems  : matched on (judge, account, slug) then (judge, account, external_id).
  - Submissions: matched on external_id within their problem.
  - Activity   : matched on (judge, account, day); counts merged by taking the max.

Each problem/activity row carries the judge `account` it was synced from, so
multi-account data round-trips and stays independently unsyncable after import.

Edits converge with a "newest wins" rule on a small set of user-editable
fields, using each problem's `updated_at`.

Judge credentials (session cookies) are intentionally NOT exported — secrets
should not travel in a plaintext data file.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..models import ActivityDay, Problem, Submission, User
from .revision import compute_next_revision

EXPORT_VERSION = 1

# User-editable fields reconciled with "newest updated_at wins" on merge.
_MERGEABLE_FIELDS = ("confidence", "revisit", "approach", "status", "last_revised")


def _acc(account: str | None) -> str:
    """Normalized account key (empty string for NULL/legacy) for dedup maps."""
    return (account or "").strip().lower()


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _comparable(dt: datetime | None) -> datetime | None:
    """Normalize to naive UTC so naive/aware values compare safely.

    SQLite may round-trip a tz-aware timestamp, while an exported value can be
    naive; coerce both to the same basis before comparing.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _problem_to_dict(problem: Problem) -> dict:
    return {
        "judge": problem.judge,
        "account": problem.account,
        "external_id": problem.external_id,
        "slug": problem.slug,
        "title": problem.title,
        "url": problem.url,
        "difficulty": problem.difficulty,
        "topics": problem.topics,
        "languages": problem.languages,
        "status": problem.status,
        "date_solved": _iso(problem.date_solved),
        "first_solved_at": _iso(problem.first_solved_at),
        "last_revised": _iso(problem.last_revised),
        "next_revision": _iso(problem.next_revision),
        "confidence": problem.confidence,
        "revisit": problem.revisit,
        "approach": problem.approach,
        "source": problem.source,
        "submissions_fetched": problem.submissions_fetched,
        "created_at": _iso(problem.created_at),
        "updated_at": _iso(problem.updated_at),
        "submissions": [_submission_to_dict(s) for s in problem.submissions],
    }


def _submission_to_dict(sub: Submission) -> dict:
    return {
        "external_id": sub.external_id,
        "lang": sub.lang,
        "status": sub.status,
        "runtime": sub.runtime,
        "memory": sub.memory,
        "submitted_at": _iso(sub.submitted_at),
        "url": sub.url,
        "code": sub.code,
    }


def export_data(db: Session, user: User) -> dict:
    """Serialize the user's problems (+ submissions) and activity to a dict."""
    problems = db.execute(
        select(Problem).where(Problem.user_id == user.id).order_by(Problem.id)
    ).scalars().all()
    activity = db.execute(
        select(ActivityDay).where(ActivityDay.user_id == user.id).order_by(ActivityDay.id)
    ).scalars().all()

    return {
        "prepvault_export": {
            "version": EXPORT_VERSION,
            "app_version": __version__,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "problems": [_problem_to_dict(p) for p in problems],
            "activity_days": [
                {
                    "judge": a.judge,
                    "account": a.account,
                    "day": _iso(a.day),
                    "count": a.count,
                }
                for a in activity
            ],
        }
    }


def _new_submission(user_id: int, problem_id: int, sd: dict) -> Submission:
    return Submission(
        user_id=user_id,
        problem_id=problem_id,
        external_id=sd["external_id"],
        lang=sd.get("lang"),
        status=sd.get("status"),
        runtime=sd.get("runtime"),
        memory=sd.get("memory"),
        submitted_at=_parse_datetime(sd.get("submitted_at")),
        url=sd.get("url"),
        code=sd.get("code"),
    )


def _new_problem(user_id: int, pd: dict) -> Problem:
    return Problem(
        user_id=user_id,
        judge=pd.get("judge") or "LeetCode",
        account=pd.get("account"),
        external_id=pd.get("external_id"),
        slug=pd.get("slug"),
        title=pd.get("title") or (pd.get("slug") or "Untitled"),
        url=pd.get("url"),
        difficulty=pd.get("difficulty"),
        topics=pd.get("topics"),
        languages=pd.get("languages"),
        status=pd.get("status") or "solved",
        date_solved=_parse_date(pd.get("date_solved")),
        first_solved_at=_parse_datetime(pd.get("first_solved_at")),
        last_revised=_parse_date(pd.get("last_revised")),
        confidence=pd.get("confidence"),
        revisit=bool(pd.get("revisit", False)),
        approach=pd.get("approach"),
        source=pd.get("source") or "sync",
        submissions_fetched=bool(pd.get("submissions_fetched", False)),
    )


def import_data(db: Session, user: User, payload: dict) -> dict:
    """Merge an exported file into the user's data without duplication."""
    envelope = (payload or {}).get("prepvault_export")
    if not isinstance(envelope, dict):
        raise ValueError("Not a PrepVault export file (missing 'prepvault_export').")
    version = envelope.get("version")
    if version != EXPORT_VERSION:
        raise ValueError(
            f"Unsupported export version {version!r}; this build reads v{EXPORT_VERSION}."
        )

    existing = db.execute(
        select(Problem).where(Problem.user_id == user.id)
    ).scalars().all()
    by_slug: dict[tuple[str, str, str], Problem] = {
        (p.judge.lower(), _acc(p.account), p.slug.lower()): p for p in existing if p.slug
    }
    by_extid: dict[tuple[str, str, str], Problem] = {
        (p.judge.lower(), _acc(p.account), p.external_id): p
        for p in existing if p.external_id
    }

    problems_added = 0
    problems_merged = 0
    submissions_added = 0

    for pd in envelope.get("problems") or []:
        judge = (pd.get("judge") or "").lower()
        account = _acc(pd.get("account"))
        slug = (pd.get("slug") or "").lower()
        extid = pd.get("external_id")
        match = None
        if slug:
            match = by_slug.get((judge, account, slug))
        if match is None and extid:
            match = by_extid.get((judge, account, extid))

        if match is None:
            problem = _new_problem(user.id, pd)
            problem.next_revision = compute_next_revision(problem)
            db.add(problem)
            db.flush()  # assign id for submissions
            for sd in pd.get("submissions") or []:
                if not sd.get("external_id"):
                    continue
                db.add(_new_submission(user.id, problem.id, sd))
                submissions_added += 1
            problems_added += 1
            if problem.slug:
                by_slug[(problem.judge.lower(), _acc(problem.account), problem.slug.lower())] = problem
            if problem.external_id:
                by_extid[(problem.judge.lower(), _acc(problem.account), problem.external_id)] = problem
        else:
            submissions_added += _merge_into(db, user, match, pd)
            problems_merged += 1

    activity_days_added = _merge_activity(db, user, envelope.get("activity_days") or [])

    db.commit()

    parts = [f"{problems_added} new problem(s)"]
    if problems_merged:
        parts.append(f"{problems_merged} merged")
    if submissions_added:
        parts.append(f"{submissions_added} submission(s)")
    if activity_days_added:
        parts.append(f"{activity_days_added} activity day(s)")
    return {
        "problems_added": problems_added,
        "problems_merged": problems_merged,
        "submissions_added": submissions_added,
        "activity_days_added": activity_days_added,
        "message": "Imported " + ", ".join(parts) + ".",
    }


def _merge_into(db: Session, user: User, problem: Problem, pd: dict) -> int:
    """Add any new submissions and reconcile editable fields (newest wins)."""
    existing_ids = {s.external_id for s in problem.submissions}
    added = 0
    for sd in pd.get("submissions") or []:
        ext = sd.get("external_id")
        if not ext or ext in existing_ids:
            continue
        db.add(_new_submission(user.id, problem.id, sd))
        existing_ids.add(ext)
        added += 1

    incoming_updated = _comparable(_parse_datetime(pd.get("updated_at")))
    local_updated = _comparable(problem.updated_at)
    if incoming_updated and (local_updated is None or incoming_updated > local_updated):
        if pd.get("confidence") is not None:
            problem.confidence = pd.get("confidence")
        if pd.get("approach"):
            problem.approach = pd.get("approach")
        if pd.get("status"):
            problem.status = pd.get("status")
        problem.revisit = bool(pd.get("revisit", problem.revisit))
        last_revised = _parse_date(pd.get("last_revised"))
        if last_revised:
            problem.last_revised = last_revised
    # Backfill metadata that was missing locally.
    if not problem.difficulty and pd.get("difficulty"):
        problem.difficulty = pd.get("difficulty")
    if not problem.topics and pd.get("topics"):
        problem.topics = pd.get("topics")
    problem.next_revision = compute_next_revision(problem)
    return added


def _merge_activity(db: Session, user: User, rows: list[dict]) -> int:
    existing = db.execute(
        select(ActivityDay).where(ActivityDay.user_id == user.id)
    ).scalars().all()
    index: dict[tuple[str, str, date], ActivityDay] = {
        (a.judge.lower(), _acc(a.account), a.day): a for a in existing
    }
    added = 0
    for row in rows:
        day = _parse_date(row.get("day"))
        judge = row.get("judge")
        if not day or not judge:
            continue
        account = row.get("account")
        count = int(row.get("count") or 0)
        key = (judge.lower(), _acc(account), day)
        current = index.get(key)
        if current is None:
            current = ActivityDay(
                user_id=user.id, judge=judge, account=account, day=day, count=count
            )
            db.add(current)
            index[key] = current
            added += 1
        else:
            current.count = max(current.count, count)
    return added
