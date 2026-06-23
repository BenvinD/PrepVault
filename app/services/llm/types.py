# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Typed request/response models for the LLM gateway boundary.

Callers never see raw vendor payloads — only these typed results. This keeps
the rest of the app decoupled from whatever the gateway speaks underneath
(OpenAI-compatible HTTP today, our own gateway SDK tomorrow).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str


class Usage(BaseModel):
    """Token accounting, surfaced for future metering/billing in the gateway."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CompletionResult(BaseModel):
    text: str
    model: str
    usage: Usage = Usage()


class EmbeddingResult(BaseModel):
    """One embedding vector per input text, in input order."""

    vectors: list[list[float]]
    model: str
    usage: Usage = Usage()


class UsageEvent(BaseModel):
    """A metering event emitted per gateway call.

    The real consumer (billing/rate-limiting) lives in the standalone gateway
    service; here we only define the shape and emit via a pluggable sink.
    """

    kind: Literal["complete", "embed"]
    model: str
    usage: Usage
    latency_ms: float
    user_id: int | None = None
