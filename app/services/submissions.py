# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Fetch + persist per-problem submissions and refresh derived fields.

The submission history is the source of truth for:
  - first_solved_at : earliest accepted submission (date + time)
  - last_revised    : date of the most recent accepted submission
  - languages       : the program(s) the problem was solved in
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Problem, Submission, User
from ..providers import get_provider
from ..providers.languages import normalize_language, normalize_languages
from .activity import store_calendar
from .resilience import guard_judge_call
from .revision import compute_next_revision
from .sync import enrich_metadata, get_all_credentials, get_credentials

ACCEPTED = {"accepted", "ac"}


def _is_accepted(status: str | None) -> bool:
    return (status or "").strip().lower() in ACCEPTED


def _provider_or_none(judge: str):
    try:
        return get_provider(judge)
    except KeyError:
        return None


def fetch_and_store(db: Session, user: User, problem: Problem, refresh: bool = False) -> list[Submission]:
    """Return stored submissions, auto-fetching from the judge when possible.

    For judges without a syncable submissions API (e.g. HelloInterview) or when
    no credentials are saved, this simply returns whatever has been recorded
    (including manual entries) instead of raising.
    """
    judge = problem.judge.lower()
    provider = _provider_or_none(judge)
    creds = get_credentials(db, user, judge, problem.account)
    can_auto = bool(
        provider
        and provider.supports_submissions
        and problem.slug
        and provider.has_credentials(creds)
    )
    if not can_auto or (problem.submissions_fetched and not refresh):
        return _stored(db, problem.id)

    slug = problem.slug
    fetched = guard_judge_call(
        judge, lambda: provider.fetch_submissions(creds, slug), user_id=user.id
    )

    existing = {
        s.external_id: s for s in db.execute(
            select(Submission).where(Submission.problem_id == problem.id)
        ).scalars()
    }
    for sd in fetched:
        sub = existing.get(sd.external_id)
        if sub is None:
            sub = Submission(user_id=user.id, problem_id=problem.id, external_id=sd.external_id)
            db.add(sub)
            existing[sd.external_id] = sub
        sub.lang = sd.lang
        sub.status = sd.status
        sub.runtime = sd.runtime
        sub.memory = sd.memory
        sub.submitted_at = sd.submitted_at
        sub.url = sd.url

    _refresh_problem(problem, list(existing.values()))
    problem.submissions_fetched = True
    db.commit()
    return _stored(db, problem.id)


def add_manual_submission(
    db: Session,
    user: User,
    problem: Problem,
    *,
    code: str | None,
    lang: str | None,
    status: str = "Accepted",
    runtime: str | None = None,
    memory: str | None = None,
    submitted_at: datetime | None = None,
) -> Submission:
    """Record a submission entered by hand (e.g. HelloInterview), with code."""
    sub = Submission(
        user_id=user.id,
        problem_id=problem.id,
        external_id=f"manual-{uuid.uuid4().hex[:12]}",
        lang=normalize_language(lang),
        status=status,
        runtime=runtime,
        memory=memory,
        submitted_at=submitted_at or datetime.now(timezone.utc),
        code=code,
    )
    db.add(sub)
    db.flush()
    all_subs = _stored(db, problem.id)
    _refresh_problem(problem, all_subs)
    problem.submissions_fetched = True
    db.commit()
    db.refresh(sub)
    return sub


def fetch_code(db: Session, user: User, problem: Problem, submission: Submission) -> Submission:
    if submission.code or submission.external_id.startswith("manual-"):
        return submission
    provider = get_provider(problem.judge.lower())
    creds = get_credentials(db, user, problem.judge.lower(), problem.account)
    if not provider.has_credentials(creds):
        raise RuntimeError("No saved credentials to fetch submission code.")
    ext_id = submission.external_id
    detail = guard_judge_call(
        problem.judge.lower(),
        lambda: provider.fetch_submission_code(creds, ext_id),
        user_id=user.id,
    )
    submission.code = detail.code
    if detail.lang:
        submission.lang = detail.lang
    db.commit()
    db.refresh(submission)
    return submission


def backfill_all(db: Session, user: User, judge: str | None = None, force: bool = False) -> dict:
    """Enrich the activity history across the user's judges.

    For judges with a per-problem submission API (LeetCode) this fetches every
    problem's submission history (accurate first-solved dates + multiple daily
    events). For judges that only expose an aggregate daily calendar
    (HackerRank) it pulls and stores that calendar. Runs for all the user's
    judges unless a specific one is requested.
    """
    if judge:
        judges = [judge.lower()]
    else:
        rows = db.execute(
            select(Problem.judge).where(Problem.user_id == user.id).distinct()
        ).scalars()
        judges = sorted({(j or "").lower() for j in rows if j}) or ["leetcode"]

    processed = 0
    submissions = 0
    calendar_days = 0
    enriched = 0
    done: list[str] = []
    errors: list[str] = []

    for jname in judges:
        provider = _provider_or_none(jname)
        if not provider:
            continue
        did = False

        # Enrich missing difficulty/topics from the judge's API (e.g. HackerRank).
        # This is account-agnostic (keyed by problem slug), so run it once.
        if provider.supports_metadata:
            enriched += enrich_metadata(db, user, jname)
            did = True

        # Back-fill once per connected account so each account's calendar and
        # submissions use its own credentials.
        accounts = get_all_credentials(db, user, jname) or [None]
        for creds in accounts:
            account = creds.get("account") if creds else None

            # Cheap bulk source: an aggregate daily calendar (e.g. HackerRank,
            # CodeChef). Powers the full contribution graph; per-problem
            # submissions still load lazily on click.
            if provider.supports_activity_calendar and creds and creds.get("username"):
                try:
                    calendar = guard_judge_call(
                        jname,
                        lambda c=creds: provider.fetch_activity_calendar(c),
                        user_id=user.id,
                    )
                    calendar_days += store_calendar(
                        db, user.id, provider.label, calendar, account
                    )
                    did = True
                except RuntimeError as exc:
                    errors.append(str(exc))

            # Per-problem submission backfill for judges without a calendar
            # (LeetCode): accurate first-solved dates + multiple daily events.
            elif provider.supports_submissions and provider.has_credentials(creds):
                stmt = select(Problem).where(
                    Problem.user_id == user.id, Problem.judge == provider.label
                )
                if account is not None:
                    stmt = stmt.where(Problem.account == account)
                for p in db.execute(stmt).scalars():
                    if not p.slug or (p.submissions_fetched and not force):
                        continue
                    try:
                        subs = fetch_and_store(db, user, p, refresh=force)
                        submissions += len(subs)
                        processed += 1
                    except RuntimeError:
                        continue
                did = True

        if did:
            done.append(provider.label)
        else:
            errors.append(f"{provider.label}: no saved credentials — run a sync first.")

    if not done:
        raise RuntimeError(errors[0] if errors else "Nothing to backfill. Run a sync first.")

    parts = []
    if submissions:
        parts.append(f"{submissions} submission(s) across {processed} problem(s)")
    if calendar_days:
        parts.append(f"{calendar_days} calendar day(s)")
    if enriched:
        parts.append(f"difficulty/topics for {enriched} problem(s)")
    detail = "; ".join(parts) if parts else "already up to date"
    return {
        "problems_processed": processed,
        "submissions": submissions,
        "calendar_days": calendar_days,
        "enriched": enriched,
        "judges": done,
        "message": f"Backfilled {', '.join(done)} — {detail}.",
    }


def _refresh_problem(problem: Problem, subs: list[Submission]) -> None:
    accepted = [s for s in subs if _is_accepted(s.status) and s.submitted_at]
    if accepted:
        accepted.sort(key=lambda s: s.submitted_at)
        problem.first_solved_at = accepted[0].submitted_at
        problem.date_solved = accepted[0].submitted_at.date()
        problem.last_revised = accepted[-1].submitted_at.date()
        problem.next_revision = compute_next_revision(problem)
    langs = normalize_languages(s.lang for s in (accepted or subs) if s.lang)
    if langs:
        problem.languages = ", ".join(langs)


def _stored(db: Session, problem_id: int) -> list[Submission]:
    return list(
        db.execute(
            select(Submission)
            .where(Submission.problem_id == problem_id)
            .order_by(Submission.submitted_at.desc())
        ).scalars()
    )
