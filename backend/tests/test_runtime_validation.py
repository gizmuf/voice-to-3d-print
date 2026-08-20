from __future__ import annotations

from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from services.runtime_validation import (
    is_production_environment,
    production_configuration_errors,
    validate_production_settings,
)


def _valid_settings(**overrides):
    values = {
        "auth_required": True,
        "insecure_local_dev": False,
        "public_safe_mode": True,
        "google_oauth_client_id": "google-web-client.apps.googleusercontent.com",
        "cors_origins": "https://3d.pulsai.app",
        "allow_untrusted_cad_code": False,
        "allow_platform_ai_spend": False,
        "allow_public_artifacts": False,
        "firebase_project_id": "pulsai-app",
        "firebase_storage_bucket": "pulsai-app.appspot.com",
        "byok_encryption_key": Fernet.generate_key().decode("ascii"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_local_and_ci_environments_are_not_subject_to_production_gate() -> None:
    unsafe = _valid_settings(
        auth_required=False,
        insecure_local_dev=True,
        public_safe_mode=False,
        google_oauth_client_id="",
    )

    assert not is_production_environment({})
    assert production_configuration_errors(unsafe, {}) == []
    validate_production_settings(unsafe, {})


def test_cloud_run_and_explicit_production_are_detected() -> None:
    assert is_production_environment({"K_SERVICE": "pulsai-3d-backend"})
    assert is_production_environment({"PULSAI_ENVIRONMENT": "production"})
    assert is_production_environment({"PULSAI_ENVIRONMENT": "PROD"})


def test_valid_cloud_run_configuration_passes() -> None:
    validate_production_settings(
        _valid_settings(),
        {
            "K_SERVICE": "pulsai-3d-backend",
            "PULSAI_DURABLE_ARTIFACTS": "true",
        },
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"auth_required": False}, "PULSAI_AUTH_REQUIRED"),
        ({"insecure_local_dev": True}, "PULSAI_INSECURE_LOCAL_DEV"),
        ({"public_safe_mode": False}, "PULSAI_PUBLIC_SAFE_MODE"),
        ({"google_oauth_client_id": ""}, "GOOGLE_OAUTH_CLIENT_ID"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://3d.pulsai.app"}, "CORS_ORIGINS"),
        ({"allow_untrusted_cad_code": True}, "PULSAI_ALLOW_UNTRUSTED_CAD_CODE"),
        ({"allow_platform_ai_spend": True}, "PULSAI_ALLOW_PLATFORM_AI_SPEND"),
        ({"allow_public_artifacts": True}, "PULSAI_ALLOW_PUBLIC_ARTIFACTS"),
        ({"firebase_project_id": ""}, "FIREBASE_PROJECT_ID"),
        ({"byok_encryption_key": ""}, "PULSAI_BYOK_ENCRYPTION_KEY"),
        ({"byok_encryption_key": "not-a-fernet-key"}, "valid Fernet key"),
    ],
)
def test_unsafe_production_settings_are_rejected(overrides, expected) -> None:
    with pytest.raises(RuntimeError, match=expected):
        validate_production_settings(
            _valid_settings(**overrides),
            {"K_SERVICE": "pulsai-3d-backend"},
        )


def test_durable_artifact_mode_requires_a_bucket() -> None:
    errors = production_configuration_errors(
        _valid_settings(firebase_storage_bucket=""),
        {
            "K_SERVICE": "pulsai-3d-backend",
            "PULSAI_DURABLE_ARTIFACTS": "true",
        },
    )

    assert errors == [
        "FIREBASE_STORAGE_BUCKET is required when PULSAI_DURABLE_ARTIFACTS is true"
    ]


def test_error_message_never_contains_secret_value() -> None:
    bad_secret = "sensitive-but-invalid-secret-value"

    with pytest.raises(RuntimeError) as exc_info:
        validate_production_settings(
            _valid_settings(byok_encryption_key=bad_secret),
            {"K_SERVICE": "pulsai-3d-backend"},
        )

    assert bad_secret not in str(exc_info.value)
