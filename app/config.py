# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Application configuration.

Two deployment modes, selected by APP_MODE:

  - "local" (default): single implicit user, no auth, SQLite on disk. Perfect
    for running on your own machine — your data never leaves it. Everything
    must work zero-config: no Redis, no vault key, no LLM key required.
  - "cloud": multi-tenant accounts with JWT auth, intended to run against
    Postgres so many users can store their data on a hosted instance.

The same codebase serves both — only configuration changes (the "BYO-backend"
philosophy). All settings are env-driven (or via a .env file).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PrepVault"
    # "local" | "cloud"
    app_mode: str = "local"

    # SQLite by default; set to a postgresql+psycopg URL for cloud.
    database_url: str = f"sqlite:///{BASE_DIR / 'prepvault.db'}"

    # ---- Background workers (cloud) --------------------------------------
    # When set, slow/external work (sync, backfill, insights, future
    # embeddings) is enqueued onto Redis and run by a worker. When unset
    # (local default), those tasks run inline so the app stays zero-config.
    redis_url: str | None = None

    # ---- Auth (only enforced in cloud mode) ------------------------------
    secret_key: str = "dev-insecure-change-me"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # ---- LLM gateway (OpenAI-compatible) ---------------------------------
    # All AI features talk to a single gateway boundary over HTTP. Point this
    # at OpenAI/OpenRouter/Groq/a local server today, or our own gateway
    # tomorrow, with zero changes to business logic. `llm_base_url` is kept as
    # a deprecated fallback for older configs.
    llm_api_key: str | None = None
    llm_gateway_url: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_embed_model: str = "text-embedding-3-small"

    # ---- Judge-call resilience (anti-flagging + fault tolerance) ---------
    # Per-user, per-judge token bucket so sync can never hammer a judge and get
    # a user's account flagged. Generous defaults — imperceptible for normal
    # use, protective against bursts. Redis-backed when available, else
    # in-process.
    judge_rate_per_sec: float = 5.0
    judge_rate_burst: int = 10
    judge_max_retries: int = 3
    circuit_fail_threshold: int = 5
    circuit_reset_seconds: float = 30.0

    # ---- Secrets vault (envelope encryption for judge cookies, keys) -----
    # Backend is pluggable; "fernet" uses a local/KMS-sourced symmetric key,
    # "none" stores secrets as-is (local-first default — your machine only).
    vault_backend: str = "none"  # "none" | "fernet"
    vault_key: str | None = None  # urlsafe base64 Fernet key (from KMS/secret mgr)

    @property
    def is_cloud(self) -> bool:
        return self.app_mode.lower() == "cloud"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return "postgresql" in self.database_url or self.database_url.startswith("postgres")

    @property
    def workers_enabled(self) -> bool:
        """True when a Redis URL is configured; otherwise tasks run inline."""
        return bool(self.redis_url)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def effective_gateway_url(self) -> str:
        """Base URL the LLM gateway client speaks to (OpenAI-compatible)."""
        return (self.llm_gateway_url or self.llm_base_url).rstrip("/")

    @property
    def vault_enabled(self) -> bool:
        return self.vault_backend.lower() == "fernet" and bool(self.vault_key)

    @property
    def vector_search_enabled(self) -> bool:
        """Second-brain vector features require Postgres (pgvector). Gated off
        in local/SQLite mode. Not built yet — exposed as a forward-looking flag.
        """
        return self.is_postgres


@lru_cache
def get_settings() -> Settings:
    return Settings()
