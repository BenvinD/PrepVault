# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""encrypt existing judge credentials at rest

Idempotently passes existing JudgeCredential secrets through the configured
secrets vault. A no-op for the local-first passthrough backend (VAULT_BACKEND
unset/none); when VAULT_BACKEND=fernet it encrypts any plaintext rows. Safe to
re-run because the vault skips values that are already encrypted.

Revision ID: a1b2c3d4e5f6
Revises: 0c2318d5b440
Create Date: 2026-06-22 21:20:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "0c2318d5b440"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.config import get_settings
    from app.security import get_vault

    settings = get_settings()
    if settings.vault_backend.lower() != "fernet":
        return  # passthrough backend — nothing to encrypt

    vault = get_vault()
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, session_cookie, csrftoken FROM judge_credentials")
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE judge_credentials "
                "SET session_cookie = :s, csrftoken = :c WHERE id = :i"
            ),
            {
                "s": vault.encrypt(row.session_cookie),
                "c": vault.encrypt(row.csrftoken),
                "i": row.id,
            },
        )


def downgrade() -> None:
    # Secrets intentionally stay encrypted on downgrade.
    pass
