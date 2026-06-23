# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""LLM gateway boundary — the single seam every AI feature depends on."""

from __future__ import annotations

from .gateway import LLMGatewayClient, LLMGatewayError, get_gateway
from .types import (
    ChatMessage,
    CompletionResult,
    EmbeddingResult,
    Usage,
    UsageEvent,
)

__all__ = [
    "LLMGatewayClient",
    "LLMGatewayError",
    "get_gateway",
    "ChatMessage",
    "CompletionResult",
    "EmbeddingResult",
    "Usage",
    "UsageEvent",
]
