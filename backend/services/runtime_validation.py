"""Fail-closed validation for network production deployments.

The checks in this module intentionally run before FastAPI accepts traffic.
Local development and CI remain unaffected unless they explicitly identify
as production through ``K_SERVICE`` or ``PULSAI_ENVIRONMENT=production``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


_PRODUCTION_NAMES = frozenset({"prod", "production"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def is_production_environment(environ: Mapping[str, str]) -> bool:
    """Return whether this process is intended to serve production traffic."""
    explicit = environ.get("PULSAI_ENVIRONMENT", "").strip().lower()
    return explicit in _PRODUCTION_NAMES or bool(environ.get("K_SERVICE", "").strip())


def _env_enabled(environ: Mapping[str, str], name: str) -> bool:
    return environ.get(name, "").strip().lower() in _TRUE_VALUES


def _valid_https_origins(raw: str) -> bool:
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if not origins:
        return False
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin in {"*", "null"}
            or parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return False
    return True


def production_configuration_errors(
    settings: Any,
    environ: Mapping[str, str],
) -> list[str]:
    """Return non-secret-bearing descriptions of unsafe production settings."""
    if not is_production_environment(environ):
        return []

    errors: list[str] = []
    if not settings.auth_required:
        errors.append("PULSAI_AUTH_REQUIRED must be true")
    if settings.insecure_local_dev:
        errors.append("PULSAI_INSECURE_LOCAL_DEV must be false")
    if not settings.public_safe_mode:
        errors.append("PULSAI_PUBLIC_SAFE_MODE must be true")
    if not settings.google_oauth_client_id.strip():
        errors.append("GOOGLE_OAUTH_CLIENT_ID must be configured")
    if not _valid_https_origins(settings.cors_origins):
        errors.append("CORS_ORIGINS must contain explicit HTTPS origins")
    if settings.allow_untrusted_cad_code:
        errors.append("PULSAI_ALLOW_UNTRUSTED_CAD_CODE must be false")
    if settings.allow_platform_ai_spend:
        errors.append("PULSAI_ALLOW_PLATFORM_AI_SPEND must be false")
    if settings.allow_public_artifacts:
        errors.append("PULSAI_ALLOW_PUBLIC_ARTIFACTS must be false")
    if not settings.firebase_project_id.strip():
        errors.append("FIREBASE_PROJECT_ID must be configured for durable state")

    encryption_key = settings.byok_encryption_key.strip()
    if not encryption_key:
        errors.append("PULSAI_BYOK_ENCRYPTION_KEY must be configured")
    else:
        try:
            Fernet(encryption_key.encode("ascii"))
        except (ValueError, UnicodeEncodeError):
            errors.append("PULSAI_BYOK_ENCRYPTION_KEY must be a valid Fernet key")

    if _env_enabled(environ, "PULSAI_DURABLE_ARTIFACTS"):
        if not settings.firebase_storage_bucket.strip():
            errors.append(
                "FIREBASE_STORAGE_BUCKET is required when PULSAI_DURABLE_ARTIFACTS is true"
            )

    return errors


def validate_production_settings(
    settings: Any,
    environ: Mapping[str, str],
) -> None:
    """Raise before startup when a production deployment is unsafe."""
    errors = production_configuration_errors(settings, environ)
    if errors:
        raise RuntimeError(
            "Unsafe Pulsai production configuration: " + "; ".join(errors)
        )


__all__ = [
    "is_production_environment",
    "production_configuration_errors",
    "validate_production_settings",
]
