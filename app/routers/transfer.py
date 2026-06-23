# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Export / import endpoints for moving tracker data between machines."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import User
from ..schemas import ImportResult
from ..services import transfer

router = APIRouter(prefix="/api", tags=["transfer"])


@router.get("/export")
def export_data(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    data = transfer.export_data(db, user)
    filename = f"prepvault-export-{date.today().isoformat()}.json"
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ImportResult)
def import_data(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ImportResult:
    try:
        result = transfer.import_data(db, user, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return ImportResult(**result)
