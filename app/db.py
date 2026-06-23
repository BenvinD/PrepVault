# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Database engine and session management.

The engine URL decides the backend: SQLite for local-first use, Postgres (or
any SQLAlchemy-supported DB) for the hosted deployment. Nothing else in the
app needs to know which one is active.

Schema changes are managed exclusively by Alembic (see app/migrations). On
startup we bring the database up to `head`; a database created before Alembic
was adopted is detected and stamped automatically so local installs upgrade
seamlessly with zero config.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent.parent

connect_args = {"check_same_thread": False} if settings.is_sqlite else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def init_db() -> None:
    """Bring the database schema up to head via Alembic migrations.

    Three cases, all handled with no manual steps:
      - fresh database  -> run every migration (creates all tables)
      - legacy database (tables exist but no alembic_version) -> stamp the
        baseline as applied, then run any later migrations
      - managed database -> upgrade to head
    """
    from alembic import command
    from alembic.script import ScriptDirectory

    from . import models  # noqa: F401  (register models on Base.metadata)

    cfg = _alembic_config()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_version_table = "alembic_version" in tables
    has_app_tables = bool(tables - {"alembic_version"})

    if not has_version_table and has_app_tables:
        # Adopt a pre-Alembic database: its schema matches the baseline, so
        # mark the baseline applied before running subsequent migrations.
        base_revision = ScriptDirectory.from_config(cfg).get_base()
        command.stamp(cfg, base_revision)

    command.upgrade(cfg, "head")
