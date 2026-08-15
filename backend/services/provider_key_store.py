"""Encrypted, account-scoped persistence for customer provider API keys.

Plaintext credentials exist only while handling a request. Firestore stores
Fernet ciphertext under a document id derived from the authenticated Google
subject. API responses expose presence booleans, never key material.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken
from firebase_admin import firestore as admin_firestore

from config import settings
from services import job_store


logger = logging.getLogger(__name__)
COLLECTION = "three_d_provider_keys"
PROVIDERS = ("anthropic", "openai", "gemini", "meshy", "tripo")


def _document_id(owner_id: str) -> str:
    return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    raw = settings.byok_encryption_key.strip()
    if not raw:
        raise RuntimeError("Provider-key persistence is not configured.")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Provider-key encryption is misconfigured.") from exc


def _client():
    try:
        return job_store._get_firestore()
    except Exception as exc:
        logger.warning("Provider-key storage is unavailable: %s", type(exc).__name__)
        return None


def persistence_configured() -> bool:
    if not settings.byok_encryption_key.strip():
        return False
    try:
        _fernet()
    except RuntimeError:
        return False
    return _client() is not None


def _encrypt(owner_id: str, provider: str, api_key: str) -> str:
    payload = json.dumps(
        {
            "version": 1,
            "owner_id": owner_id,
            "provider": provider,
            "api_key": api_key,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return _fernet().encrypt(payload).decode("ascii")


def _decrypt(owner_id: str, provider: str, ciphertext: str) -> str | None:
    try:
        payload = json.loads(_fernet().decrypt(ciphertext.encode("ascii")))
    except (InvalidToken, ValueError, TypeError, UnicodeEncodeError, json.JSONDecodeError):
        logger.warning("Ignoring an unreadable stored %s provider credential.", provider)
        return None
    if not isinstance(payload, dict):
        logger.warning("Ignoring an unreadable stored %s provider credential.", provider)
        return None
    if (
        payload.get("version") != 1
        or payload.get("owner_id") != owner_id
        or payload.get("provider") != provider
    ):
        logger.warning("Ignoring a provider credential with mismatched account binding.")
        return None
    value = str(payload.get("api_key") or "")
    return value or None


def load_provider_keys(owner_id: str) -> dict[str, str]:
    client = _client()
    if client is None or not settings.byok_encryption_key.strip():
        return {}
    try:
        snapshot = client.collection(COLLECTION).document(_document_id(owner_id)).get()
    except Exception as exc:
        logger.warning("Provider-key read failed: %s", type(exc).__name__)
        return {}
    if not snapshot.exists:
        return {}
    encrypted = (snapshot.to_dict() or {}).get("encrypted_keys") or {}
    if not isinstance(encrypted, dict):
        return {}
    out: dict[str, str] = {}
    for provider in PROVIDERS:
        ciphertext = encrypted.get(provider)
        if not isinstance(ciphertext, str):
            continue
        value = _decrypt(owner_id, provider, ciphertext)
        if value:
            out[provider] = value
    return out


def provider_key_presence(owner_id: str) -> dict[str, bool]:
    stored = load_provider_keys(owner_id)
    return {provider: provider in stored for provider in PROVIDERS}


def store_provider_keys(owner_id: str, updates: Mapping[str, str]) -> dict[str, bool]:
    client = _client()
    if client is None:
        raise RuntimeError("Provider-key persistence is unavailable.")
    encrypted: dict[str, str] = {}
    for provider, value in updates.items():
        if provider not in PROVIDERS:
            raise ValueError("Unsupported provider.")
        encrypted[provider] = _encrypt(owner_id, provider, value)
    if not encrypted:
        return provider_key_presence(owner_id)

    document = client.collection(COLLECTION).document(_document_id(owner_id))
    try:
        document.set(
            {
                "owner_hash": _document_id(owner_id),
                "encrypted_keys": encrypted,
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    except Exception as exc:
        logger.warning("Provider-key write failed: %s", type(exc).__name__)
        raise RuntimeError("Provider-key persistence failed.") from exc
    return provider_key_presence(owner_id)


def clear_provider_keys(owner_id: str) -> None:
    client = _client()
    if client is None:
        raise RuntimeError("Provider-key persistence is unavailable.")
    try:
        client.collection(COLLECTION).document(_document_id(owner_id)).delete()
    except Exception as exc:
        logger.warning("Provider-key deletion failed: %s", type(exc).__name__)
        raise RuntimeError("Provider-key deletion failed.") from exc


__all__ = [
    "PROVIDERS",
    "clear_provider_keys",
    "load_provider_keys",
    "persistence_configured",
    "provider_key_presence",
    "store_provider_keys",
]
