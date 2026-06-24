# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Unification layer: turn raw DB models into a single, judge-agnostic shape.

Every judge reports difficulty, status, language, and topics differently. This
module is the one place that maps all of it onto a consistent contract so the
frontend renders identically regardless of where the data came from:

    judge       -> {name, label, color}
    difficulty  -> {label, rank, color}   (Easy/Medium/Hard, normalized)
    status      -> {label, accepted, color}
    languages   -> ["C++", "Python", ...] (normalized + de-duplicated)
    topics      -> ["Array", "Hash Map", ...]

Routers should serialize through `unify_problem` / `unify_submission` so no
endpoint leaks provider-specific naming to the client.
"""

from __future__ import annotations

from ..models import Problem, Submission
from ..providers import REGISTRY
from ..providers.languages import normalize_language, normalize_languages

# difficulty token -> (label, sort rank, pill color class)
_DIFFICULTY: dict[str, tuple[str, int, str]] = {
    "easy": ("Easy", 1, "easy"),
    "basic": ("Easy", 1, "easy"),
    "beginner": ("Easy", 1, "easy"),
    "medium": ("Medium", 2, "medium"),
    "med": ("Medium", 2, "medium"),
    "intermediate": ("Medium", 2, "medium"),
    "hard": ("Hard", 3, "hard"),
    "difficult": ("Hard", 3, "hard"),
    "expert": ("Hard", 3, "hard"),
    "advanced": ("Hard", 3, "hard"),
}

_ACCEPTED = {"accepted", "ac", "passed", "solved", "success", "correct"}


def difficulty_meta(raw: str | None) -> dict:
    label, rank, color = _DIFFICULTY.get((raw or "").strip().lower(), (None, 0, ""))
    return {"label": label, "rank": rank, "color": color}


def status_meta(raw: str | None) -> dict:
    s = (raw or "").strip()
    low = s.lower()
    if not s:
        return {"label": "—", "accepted": False, "color": ""}
    if low in _ACCEPTED or "accept" in low:
        return {"label": "Accepted", "accepted": True, "color": "easy"}
    if "partial" in low:
        return {"label": "Partially Accepted", "accepted": False, "color": "medium"}
    if any(k in low for k in ("pending", "queue", "processing", "running")):
        return {"label": s, "accepted": False, "color": "medium"}
    if "wrong" in low:
        return {"label": "Wrong Answer", "accepted": False, "color": "hard"}
    if any(k in low for k in ("time", "tle", "timeout")):
        return {"label": "Time Limit Exceeded", "accepted": False, "color": "hard"}
    if "compil" in low:
        return {"label": "Compile Error", "accepted": False, "color": "hard"}
    if "runtime" in low:
        return {"label": "Runtime Error", "accepted": False, "color": "hard"}
    if "memory" in low:
        return {"label": "Memory Limit Exceeded", "accepted": False, "color": "hard"}
    return {"label": s, "accepted": False, "color": "hard"}


def provider_meta(judge: str | None) -> dict:
    key = (judge or "").strip().lower()
    prov = REGISTRY.get(key)
    if prov is None:
        prov = next((p for p in REGISTRY.values() if p.label.lower() == key), None)
    if prov is not None:
        return {"name": prov.name, "label": prov.label, "color": getattr(prov, "color", "#6366f1")}
    return {"name": key, "label": judge or "Unknown", "color": "#6366f1"}


def split_topics(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def unify_problem(p: Problem) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "slug": p.slug,
        "external_id": p.external_id,
        "url": p.url,
        "judge": provider_meta(p.judge),
        "difficulty": difficulty_meta(p.difficulty),
        "topics": split_topics(p.topics),
        "languages": normalize_languages(split_topics(p.languages)),
        "status": p.status,
        "date_solved": p.date_solved,
        "first_solved_at": p.first_solved_at,
        "last_revised": p.last_revised,
        "next_revision": p.next_revision,
        "confidence": p.confidence,
        "revisit": p.revisit,
        "approach": p.approach,
        "notes": p.notes,
        "source": p.source,
        "submissions_fetched": p.submissions_fetched,
    }


def unify_submission(s: Submission) -> dict:
    return {
        "id": s.id,
        "external_id": s.external_id,
        "lang": normalize_language(s.lang),
        "status": status_meta(s.status),
        "runtime": s.runtime,
        "memory": s.memory,
        "submitted_at": s.submitted_at,
        "url": s.url,
        "has_code": bool(s.code),
    }
