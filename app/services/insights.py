# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""LLM-generated 'key insight' for a problem.

This service depends ONLY on the LLM gateway boundary (`services/llm`). It does
not import any model SDK or make raw HTTP calls — swapping providers or pointing
at our own gateway is purely a config change.
"""

from __future__ import annotations

from .llm import ChatMessage, LLMGatewayError, get_gateway

SYSTEM_PROMPT = (
    "You are a competitive-programming mentor. Given a coding problem, reply with "
    "a single short 'key insight' that captures the optimal approach. Rules: 1-3 "
    "sentences, under ~60 words, plain prose (no markdown, no headings, no code "
    "blocks). Focus on the core technique and why it works."
)


class InsightError(RuntimeError):
    pass


def generate_insight(
    title: str,
    difficulty: str | None,
    topics: str | None,
    url: str | None,
    *,
    user_id: int | None = None,
) -> str:
    gateway = get_gateway()
    if not gateway.enabled:
        raise InsightError("LLM is not configured. Set LLM_API_KEY to enable insights.")

    parts = [f"Problem: {title}"]
    if difficulty:
        parts.append(f"Difficulty: {difficulty}")
    if topics:
        parts.append(f"Topics: {topics}")
    if url:
        parts.append(f"URL: {url}")
    user_msg = "\n".join(parts) + "\n\nGive the key insight."

    try:
        result = gateway.complete(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=user_msg),
            ],
            temperature=0.3,
            max_tokens=160,
            user_id=user_id,
        )
    except LLMGatewayError as exc:
        raise InsightError(str(exc)) from exc
    return result.text
