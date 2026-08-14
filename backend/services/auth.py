"""Request-scoped Google identity verification and design ownership helpers."""

from __future__ import annotations

import hashlib
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


@dataclass(frozen=True)
class Principal:
    subject: str
    email: str = ""
    name: str = ""


_principal: ContextVar[Principal | None] = ContextVar("pulsai_principal", default=None)
_cache: dict[str, tuple[float, Principal]] = {}
_cache_lock = Lock()


def set_current_principal(principal: Principal | None) -> Token:
    return _principal.set(principal)


def reset_current_principal(token: Token) -> None:
    _principal.reset(token)


def current_principal() -> Principal | None:
    return _principal.get()


def current_owner_id() -> str | None:
    principal = current_principal()
    return principal.subject if principal else None


def verify_google_credential(credential: str, audience: str) -> Principal:
    """Verify a Google Identity Services ID token, with a short bounded cache."""
    if not credential or not audience:
        raise ValueError("Google authentication is not configured.")
    digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    now = time.time()
    with _cache_lock:
        cached = _cache.get(digest)
        if cached and cached[0] > now:
            return cached[1]

    claims: dict[str, Any] = id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        audience,
    )
    issuer = str(claims.get("iss") or "")
    subject = str(claims.get("sub") or "")
    if issuer not in {"accounts.google.com", "https://accounts.google.com"} or not subject:
        raise ValueError("Invalid Google token issuer or subject.")
    if claims.get("email") and claims.get("email_verified") is not True:
        raise ValueError("Google account email is not verified.")

    principal = Principal(
        subject=subject,
        email=str(claims.get("email") or ""),
        name=str(claims.get("name") or ""),
    )
    expiry = float(claims.get("exp") or now + 60)
    cache_until = min(expiry, now + 300)
    with _cache_lock:
        _cache[digest] = (cache_until, principal)
        if len(_cache) > 2048:
            stale = [key for key, (expires, _) in _cache.items() if expires <= now]
            for key in stale:
                _cache.pop(key, None)
    return principal


__all__ = [
    "Principal",
    "current_owner_id",
    "current_principal",
    "reset_current_principal",
    "set_current_principal",
    "verify_google_credential",
]
