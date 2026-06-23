# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Sync orchestration: pull from a judge provider and upsert into the DB."""

from __future__ import annotations

import time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import ActivityDay, JudgeCredential, Problem, User
from ..providers import REGISTRY, get_provider
from ..schemas import SyncResult
from ..security import get_vault
from .presentation import provider_meta
from .resilience import guard_judge_call
from .revision import compute_next_revision

_META_SYNC_CAP = 80  # max problems to enrich inline during a sync


def _norm_account(account: str | None) -> str | None:
    a = (account or "").strip()
    return a or None


def _account_of(credentials: dict, account: str | None = None) -> str | None:
    return _norm_account(account) or _norm_account(credentials.get("username"))


def store_credentials(
    db: Session, user: User, judge: str, credentials: dict, account: str | None = None
) -> None:
    """Persist judge credentials (per account) so submissions can be fetched later."""
    session = credentials.get("session_cookie") or credentials.get("leetcode_session")
    account = _account_of(credentials, account)
    if not (session or account):
        return
    # One credential row per (user, judge, account). Match the account
    # case-insensitively; NULL account is the legacy/unresolved single row.
    stmt = select(JudgeCredential).where(
        JudgeCredential.user_id == user.id, JudgeCredential.judge == judge.lower()
    )
    if account is None:
        stmt = stmt.where(
            or_(JudgeCredential.username.is_(None), JudgeCredential.username == "")
        )
    else:
        stmt = stmt.where(func.lower(JudgeCredential.username) == account.lower())
    cred = db.execute(stmt).scalars().first()
    if cred is None:
        cred = JudgeCredential(user_id=user.id, judge=judge.lower())
        db.add(cred)
    vault = get_vault()
    # Secrets (session cookie, csrf token) are encrypted at rest; username is
    # not a secret. Only overwrite when a new value is supplied.
    if session:
        cred.session_cookie = vault.encrypt(session)
    new_csrf = credentials.get("csrftoken")
    if new_csrf:
        cred.csrftoken = vault.encrypt(new_csrf)
    if account:
        cred.username = account


def _cred_to_dict(cred: JudgeCredential) -> dict:
    vault = get_vault()
    session = vault.decrypt(cred.session_cookie)
    return {
        "session_cookie": session,
        "leetcode_session": session,  # alias for the LeetCode provider
        "csrftoken": vault.decrypt(cred.csrftoken),
        "username": cred.username,
        "account": cred.username,
    }


def get_credentials(
    db: Session, user: User, judge: str, account: str | None = None
) -> dict | None:
    """Return credentials for a judge account, or any account when unspecified."""
    account = _norm_account(account)
    stmt = select(JudgeCredential).where(
        JudgeCredential.user_id == user.id, JudgeCredential.judge == judge.lower()
    )
    if account is not None:
        stmt = stmt.where(func.lower(JudgeCredential.username) == account.lower())
    cred = db.execute(stmt).scalars().first()
    if not cred and account is not None:
        # Fall back to a legacy/unattributed row for this judge.
        cred = db.execute(
            select(JudgeCredential).where(
                JudgeCredential.user_id == user.id,
                JudgeCredential.judge == judge.lower(),
            )
        ).scalars().first()
    if not cred:
        return None
    return _cred_to_dict(cred)


def get_all_credentials(db: Session, user: User, judge: str) -> list[dict]:
    """All stored credential accounts for a judge (one dict per account)."""
    creds = db.execute(
        select(JudgeCredential).where(
            JudgeCredential.user_id == user.id, JudgeCredential.judge == judge.lower()
        )
    ).scalars().all()
    return [_cred_to_dict(c) for c in creds]


def enrich_metadata(
    db: Session, user: User, judge: str, problem_ids: list[int] | None = None
) -> int:
    """Fill missing difficulty/topics for a judge's problems from its API.

    Targets the given problem ids, or every problem of that judge still missing
    a difficulty. Returns how many problems were updated.
    """
    try:
        provider = get_provider(judge)
    except KeyError:
        return 0
    if not provider.supports_metadata:
        return 0

    stmt = select(Problem).where(Problem.user_id == user.id, Problem.judge == provider.label)
    if problem_ids is not None:
        if not problem_ids:
            return 0
        stmt = stmt.where(Problem.id.in_(problem_ids))
    else:
        stmt = stmt.where(Problem.difficulty.is_(None))

    updated = 0
    for problem in db.execute(stmt).scalars():
        if not problem.slug:
            continue
        slug = problem.slug
        try:
            meta = guard_judge_call(
                judge, lambda: provider.fetch_problem_meta(slug), user_id=user.id
            )
        except Exception:  # noqa: BLE001 — best effort, skip failures
            meta = None
        if not meta:
            continue
        changed = False
        if meta.get("difficulty") and not problem.difficulty:
            problem.difficulty = meta["difficulty"]
            changed = True
        topics = meta.get("topics") or []
        if topics and not problem.topics:
            problem.topics = ", ".join(topics)
            changed = True
        if changed:
            updated += 1
        time.sleep(0.12)
    db.commit()
    return updated


def sync_user_problems(
    db: Session, user: User, judge: str, credentials: dict, account: str | None = None
) -> SyncResult:
    provider = get_provider(judge)
    fetched = guard_judge_call(
        judge, lambda: provider.fetch_solved(credentials), user_id=user.id
    )

    # Resolve the account these problems belong to: explicit > credential
    # username > whatever the provider stamped on the fetched records.
    account = _account_of(credentials, account)
    if account is None:
        account = next((pd.account for pd in fetched if pd.account), None)
    account = _norm_account(account)
    store_credentials(db, user, judge, credentials, account)

    label = provider.label
    acc_l = account.lower() if account else None

    # Dedup is scoped to this judge + account, so each account is tracked
    # independently and can be unsynced on its own. Legacy rows with no account
    # (NULL) are claimed by the first sync that matches them, progressively
    # attributing pre-multi-account data without creating duplicates.
    existing = db.execute(
        select(Problem).where(Problem.user_id == user.id, Problem.judge == label)
    ).scalars().all()
    by_slug: dict[str, Problem] = {}
    by_ext: dict[str, Problem] = {}
    for p in existing:
        owns = p.account is None or (acc_l and (p.account or "").lower() == acc_l)
        if not owns:
            continue
        if p.slug:
            by_slug.setdefault(p.slug.lower(), p)
        if p.external_id:
            by_ext.setdefault(p.external_id, p)

    added = 0
    skipped = 0
    claimed = 0
    new_problems: list[Problem] = []
    for pd in fetched:
        pacc = _norm_account(pd.account) or account
        slug_key = (pd.slug or "").lower()
        match = None
        if slug_key and slug_key in by_slug:
            match = by_slug[slug_key]
        elif pd.external_id and pd.external_id in by_ext:
            match = by_ext[pd.external_id]
        if match is not None:
            if match.account is None and pacc:
                match.account = pacc  # claim a legacy/unattributed row
                claimed += 1
            skipped += 1
            continue

        problem = Problem(
            user_id=user.id,
            judge=pd.judge,
            account=pacc,
            external_id=pd.external_id,
            slug=pd.slug,
            title=pd.title,
            url=pd.url,
            difficulty=pd.difficulty,
            topics=", ".join(pd.topics) if pd.topics else None,
            languages=pd.language,
            status="solved",
            date_solved=pd.date_solved,
            source="sync",
        )
        problem.next_revision = compute_next_revision(problem)
        db.add(problem)
        new_problems.append(problem)
        added += 1
        if slug_key:
            by_slug[slug_key] = problem
        if pd.external_id:
            by_ext[pd.external_id] = problem

    db.commit()

    who = f" as {account}" if account else ""
    message = (
        f"Fetched {len(fetched)} solved on {provider.label}{who}; "
        f"added {added}, skipped {skipped} duplicate(s)."
    )
    if claimed:
        message += f" Attributed {claimed} existing problem(s) to {account}."
    # Enrich difficulty/topics for the newly added problems when it's a small
    # batch; larger first-time imports are deferred to the Backfill action so
    # the sync stays responsive.
    if provider.supports_metadata and new_problems:
        new_ids = [p.id for p in new_problems if p.difficulty is None]
        if 0 < len(new_ids) <= _META_SYNC_CAP:
            enriched = enrich_metadata(db, user, judge, new_ids)
            if enriched:
                message += f" Updated difficulty for {enriched}."
        elif len(new_ids) > _META_SYNC_CAP:
            message += " Run Backfill to fetch difficulty/topics for the rest."

    return SyncResult(
        fetched=len(fetched),
        added=added,
        skipped=skipped,
        judge=provider.label,
        message=message,
    )


def list_accounts(db: Session, user: User) -> list[dict]:
    """Connected judge accounts with their problem counts, for the Sync tab.

    An entry exists for every stored credential, and for every account that owns
    synced problems. Manually-added problems (no account, no credential) are not
    listed here — they're managed per-problem.
    """
    entries: dict[tuple[str, str], dict] = {}

    def key(name: str, account: str | None) -> tuple[str, str]:
        return (name, (account or "").lower())

    creds = db.execute(
        select(JudgeCredential).where(JudgeCredential.user_id == user.id)
    ).scalars().all()
    for c in creds:
        meta = provider_meta(c.judge)
        acc = _norm_account(c.username)
        e = entries.setdefault(
            key(meta["name"], acc),
            {"judge": meta, "account": acc, "problems": 0,
             "has_credentials": False, "has_cookie": False},
        )
        e["has_credentials"] = True
        e["has_cookie"] = bool(c.session_cookie)
        if acc:
            e["account"] = acc

    counts = db.execute(
        select(Problem.judge, Problem.account, func.count(Problem.id))
        .where(Problem.user_id == user.id)
        .group_by(Problem.judge, Problem.account)
    ).all()
    for label, account, count in counts:
        meta = provider_meta(label)
        acc = _norm_account(account)
        k = key(meta["name"], acc)
        if acc is None and k not in entries:
            # NULL-account problems only surface under an existing (credentialed)
            # entry; pure manual problems don't get an account row.
            continue
        e = entries.setdefault(
            k,
            {"judge": meta, "account": acc, "problems": 0,
             "has_credentials": False, "has_cookie": False},
        )
        e["problems"] += count

    out = []
    for e in entries.values():
        name = e["judge"]["name"]
        prov = REGISTRY.get(name)
        e["syncable"] = bool(prov and prov.syncable)
        out.append(e)
    out.sort(key=lambda e: (e["judge"]["label"].lower(), (e["account"] or "")))
    return out


def unsync_account(db: Session, user: User, judge: str, account: str | None) -> dict:
    """Remove everything synced from one judge account: problems (and their
    submissions, via cascade), the activity calendar, and the stored credential.
    """
    try:
        provider = get_provider(judge)
    except KeyError as exc:
        raise RuntimeError(str(exc)) from exc
    label = provider.label
    name = provider.name
    account = _norm_account(account)

    def acc_filter(column):
        if account is None:
            return column.is_(None)
        return func.lower(column) == account.lower()

    problems = db.execute(
        select(Problem).where(
            Problem.user_id == user.id,
            Problem.judge == label,
            acc_filter(Problem.account),
        )
    ).scalars().all()
    n_problems = len(problems)
    for p in problems:
        db.delete(p)  # cascade removes submissions

    activity = db.execute(
        select(ActivityDay).where(
            ActivityDay.user_id == user.id,
            ActivityDay.judge == label,
            acc_filter(ActivityDay.account),
        )
    ).scalars().all()
    n_activity = len(activity)
    for a in activity:
        db.delete(a)

    cred_stmt = select(JudgeCredential).where(
        JudgeCredential.user_id == user.id, JudgeCredential.judge == name
    )
    if account is None:
        cred_stmt = cred_stmt.where(
            or_(JudgeCredential.username.is_(None), JudgeCredential.username == "")
        )
    else:
        cred_stmt = cred_stmt.where(func.lower(JudgeCredential.username) == account.lower())
    creds = db.execute(cred_stmt).scalars().all()
    for c in creds:
        db.delete(c)

    db.commit()
    label_acc = account or "the unattributed account"
    return {
        "judge": label,
        "account": account,
        "problems_removed": n_problems,
        "activity_days_removed": n_activity,
        "credentials_removed": len(creds),
        "message": (
            f"Unsynced {label} ({label_acc}): removed {n_problems} problem(s)"
            f"{f', {n_activity} activity day(s)' if n_activity else ''}"
            f"{', and its saved credential' if creds else ''}."
        ),
    }
