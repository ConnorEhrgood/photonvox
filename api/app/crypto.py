"""Secrets at rest (ARCHITECTURE §15): Fernet, keyed by SECRETS_KEY. A secret is encrypted before it reaches the database and decrypted only where
it is used (the worker, talking to an engine). Values are never logged or returned by the API."""
from __future__ import annotations

from typing import List

from cryptography.fernet import Fernet, MultiFernet

from app.config import settings


def _keys() -> List[str]:
    keys = [k.strip() for k in settings.secrets_key.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("SECRETS_KEY is not set")
    return keys


def _box() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _keys()])


def seal(value: str) -> str:
    return _box().encrypt(value.encode()).decode()


def unseal(token: str) -> str:
    return _box().decrypt(token.encode()).decode()
