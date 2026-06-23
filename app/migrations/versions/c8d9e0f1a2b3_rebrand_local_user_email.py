# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""rebrand local user email to local@prepvault

Renames the implicit local user's sentinel email from the old brand
(local@retrievo) to the new one (local@prepvault) so an existing local-first
database keeps all of its problems, submissions and activity attached after the
rebrand. A no-op on fresh installs (no such row) and idempotent.

Revision ID: c8d9e0f1a2b3
Revises: b7e1f2a3c4d5
Create Date: 2026-06-23 08:10:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | None = "b7e1f2a3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE users SET email = 'local@prepvault' "
            "WHERE email = 'local@retrievo'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE users SET email = 'local@retrievo' "
            "WHERE email = 'local@prepvault'"
        )
    )
