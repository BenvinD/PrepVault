# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""multi-account support: attribute problems/activity to a judge account

Adds an ``account`` column to ``problems`` and ``activity_days`` so a user can
connect multiple accounts on the same judge and unsync one cleanly, and relaxes
the credential uniqueness to (user, judge, username) so each account keeps its
own cookie/handle.

Existing rows are backfilled from the single stored credential per judge, so a
user's current data is attributed to the account they already synced.

Revision ID: b7e1f2a3c4d5
Revises: 58c9b0c82977
Create Date: 2026-06-22 22:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e1f2a3c4d5"
down_revision: str | None = "58c9b0c82977"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL = """
UPDATE {table}
SET account = (
    SELECT jc.username FROM judge_credentials jc
    WHERE jc.user_id = {table}.user_id
      AND lower(jc.judge) = lower({table}.judge)
      AND jc.username IS NOT NULL AND jc.username <> ''
    LIMIT 1
)
WHERE account IS NULL
  AND EXISTS (
    SELECT 1 FROM judge_credentials jc
    WHERE jc.user_id = {table}.user_id
      AND lower(jc.judge) = lower({table}.judge)
      AND jc.username IS NOT NULL AND jc.username <> ''
  )
"""


def upgrade() -> None:
    with op.batch_alter_table("problems", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account", sa.String(length=120), nullable=True))
        batch_op.drop_constraint("uq_user_judge_slug", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_account_slug", ["user_id", "judge", "account", "slug"]
        )
        batch_op.create_index(
            batch_op.f("ix_problems_account"), ["account"], unique=False
        )

    with op.batch_alter_table("activity_days", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account", sa.String(length=120), nullable=True))
        batch_op.drop_constraint("uq_user_judge_day", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_account_day", ["user_id", "judge", "account", "day"]
        )

    with op.batch_alter_table("judge_credentials", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_judge_cred", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_username_cred", ["user_id", "judge", "username"]
        )

    # Attribute existing problems/activity to the account already synced.
    op.execute(_BACKFILL.format(table="problems"))
    op.execute(_BACKFILL.format(table="activity_days"))


def downgrade() -> None:
    with op.batch_alter_table("judge_credentials", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_judge_username_cred", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_cred", ["user_id", "judge"]
        )

    with op.batch_alter_table("activity_days", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_judge_account_day", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_day", ["user_id", "judge", "day"]
        )
        batch_op.drop_column("account")

    with op.batch_alter_table("problems", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_problems_account"))
        batch_op.drop_constraint("uq_user_judge_account_slug", type_="unique")
        batch_op.create_unique_constraint(
            "uq_user_judge_slug", ["user_id", "judge", "slug"]
        )
        batch_op.drop_column("account")
