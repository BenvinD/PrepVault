# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Security primitives: secrets vault (envelope encryption) and friends."""

from __future__ import annotations

from .vault import Vault, VaultError, get_vault

__all__ = ["Vault", "VaultError", "get_vault"]
