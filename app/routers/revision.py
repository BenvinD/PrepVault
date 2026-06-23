# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Smart revision queue endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..services.revision import build_revision_queue

router = APIRouter(prefix="/api/revision", tags=["revision"])


@router.get("/queue")
def revision_queue(
    batch_size: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Due problems in priority order + the user's weakest topics."""
    return build_revision_queue(db, user.id, batch_size=batch_size)
