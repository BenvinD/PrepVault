# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Benvin D
#
# This file is part of PrepVault, released under the GNU Affero General
# Public License v3.0 or later. See the LICENSE file for details.
"""Secrets vault — envelope encryption for secrets stored at rest.

Judge session cookies and any server-held keys must never sit in the database
as plaintext in a hosted deployment. This module provides a small, pluggable
encryption seam:

  - "none"   : passthrough — store as-is. The local-first default, so running
               on your own machine stays zero-config (your data never leaves
               your disk anyway).
  - "fernet" : symmetric envelope encryption with a key sourced from a KMS /
               secret manager (`VAULT_KEY`). Swap the backend later (e.g. a
               real KMS-per-record data key) without touching callers.

Encrypted values are tagged with a version prefix (`enc:v1:`) so a database can
hold a mix of plaintext (pre-encryption) and ciphertext rows and be migrated
safely and idempotently. Plaintext secrets are never logged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

from ..config import Settings, get_settings

_ENC_PREFIX = "enc:v1:"


class VaultError(RuntimeError):
    pass


class Vault(ABC):
    """Encrypt/decrypt secrets for storage. Both methods are None-safe."""

    @abstractmethod
    def encrypt(self, plaintext: str | None) -> str | None:
        ...

    @abstractmethod
    def decrypt(self, stored: str | None) -> str | None:
        ...

    @staticmethod
    def is_encrypted(value: str | None) -> bool:
        return bool(value) and value.startswith(_ENC_PREFIX)


class NoneVault(Vault):
    """Passthrough vault — stores secrets as-is (local-first default)."""

    def encrypt(self, plaintext: str | None) -> str | None:
        return plaintext

    def decrypt(self, stored: str | None) -> str | None:
        return stored


class FernetVault(Vault):
    """Symmetric envelope encryption using a KMS/secret-manager-held key."""

    def __init__(self, key: str) -> None:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover
            raise VaultError(
                "cryptography is required for the fernet vault backend."
            ) from exc
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as exc:
            raise VaultError(
                "Invalid VAULT_KEY. Generate one with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"`."
            ) from exc

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None or plaintext == "":
            return plaintext
        if Vault.is_encrypted(plaintext):
            return plaintext  # already encrypted — idempotent
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_ENC_PREFIX}{token}"

    def decrypt(self, stored: str | None) -> str | None:
        if stored is None or stored == "":
            return stored
        if not Vault.is_encrypted(stored):
            return stored  # legacy plaintext row — return as-is
        token = stored[len(_ENC_PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — invalid/forged token
            raise VaultError("Failed to decrypt a stored secret (wrong VAULT_KEY?).") from exc


def _build_vault(settings: Settings) -> Vault:
    backend = settings.vault_backend.lower()
    if backend == "fernet":
        if not settings.vault_key:
            raise VaultError("VAULT_BACKEND=fernet requires VAULT_KEY to be set.")
        return FernetVault(settings.vault_key)
    return NoneVault()


@lru_cache
def get_vault() -> Vault:
    return _build_vault(get_settings())
