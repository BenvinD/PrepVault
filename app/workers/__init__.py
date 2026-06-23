# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Background worker layer.

Slow/external work (judge sync, submission backfill, AI insights, future
embeddings) runs here instead of inline in request handlers. When `REDIS_URL`
is set, work is enqueued onto Arq; otherwise the dispatcher runs it inline so
local mode stays zero-config.
"""

from __future__ import annotations

from .dispatch import dispatch

__all__ = ["dispatch"]
