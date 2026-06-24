# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""add notes column to problems for user-authored second-brain notes

Revision ID: d1e2f3a4b5c6
Revises: c8d9e0f1a2b3
Create Date: 2026-06-24 08:50:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("problems", schema=None) as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("problems", schema=None) as batch_op:
        batch_op.drop_column("notes")
