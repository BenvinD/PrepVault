# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""PrepVault FastAPI application entrypoint.

Run locally:   uvicorn app.main:app --reload
Open:          http://localhost:8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .auth import get_current_user
from .config import get_settings
from .db import init_db
from .models import User
from .providers import REGISTRY
from .routers import auth as auth_router
from .routers import jobs as jobs_router
from .routers import problems as problems_router
from .routers import revision as revision_router
from .routers import submissions as submissions_router
from .routers import sync as sync_router
from .routers import transfer as transfer_router
from .schemas import ConfigOut, ProviderOut

settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def lifespan(_: "FastAPI"):
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Local-first, self-hostable interview-prep tracker.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

meta = APIRouter(prefix="/api", tags=["meta"])


@meta.get("/config", response_model=ConfigOut)
def app_config() -> ConfigOut:
    return ConfigOut(
        app_name=settings.app_name,
        mode=settings.app_mode,
        auth_required=settings.is_cloud,
        llm_enabled=settings.llm_enabled,
        features={
            "llm": settings.llm_enabled,
            "workers": settings.workers_enabled,
            "vault": settings.vault_enabled,
            "vector_search": settings.vector_search_enabled,
        },
    )


@meta.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "email": user.email, "is_local": user.is_local}


@meta.get("/providers", response_model=list[ProviderOut])
def providers() -> list[ProviderOut]:
    return [
        ProviderOut(
            name=cls.name,
            label=cls.label,
            color=cls.color,
            syncable=cls.syncable,
            supports_submissions=cls.supports_submissions,
        )
        for cls in REGISTRY.values()
    ]


app.include_router(meta)
app.include_router(auth_router.router)
app.include_router(problems_router.router)
app.include_router(sync_router.router)
app.include_router(submissions_router.router)
app.include_router(jobs_router.router)
app.include_router(transfer_router.router)
app.include_router(revision_router.router)


# Serve the single-page frontend.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
