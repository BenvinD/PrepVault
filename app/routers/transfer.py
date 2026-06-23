# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Export / import endpoints for moving tracker data between machines."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
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
    date_from: date | None = Query(None, alias="from", description="Only problems solved on/after this date."),
    date_to: date | None = Query(None, alias="to", description="Only problems solved on/before this date."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JSONResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "'from' date must be on or before 'to' date."
        )
    data = transfer.export_data(db, user, date_from=date_from, date_to=date_to)
    if date_from or date_to:
        lo = date_from.isoformat() if date_from else "start"
        hi = date_to.isoformat() if date_to else date.today().isoformat()
        filename = f"prepvault-export-{lo}_to_{hi}.json"
    else:
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
