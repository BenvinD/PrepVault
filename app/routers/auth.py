# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Auth endpoints (cloud mode). No-ops gracefully in local mode."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import create_access_token, hash_password, verify_password
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import Credentials, Token

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


@router.post("/register", response_model=Token)
def register(creds: Credentials, db: Session = Depends(get_db)) -> Token:
    if not settings.is_cloud:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Accounts are only used in cloud mode.")
    existing = db.execute(select(User).where(User.email == creds.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered.")
    user = User(email=creds.email, hashed_password=hash_password(creds.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/login", response_model=Token)
def login(creds: Credentials, db: Session = Depends(get_db)) -> Token:
    if not settings.is_cloud:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Accounts are only used in cloud mode.")
    user = db.execute(select(User).where(User.email == creds.email)).scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(creds.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")
    return Token(access_token=create_access_token(str(user.id)))
