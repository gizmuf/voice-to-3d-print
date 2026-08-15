from __future__ import annotations

import json

from cryptography.fernet import Fernet
from fastapi import Request
from fastapi.testclient import TestClient

import app as app_module
import config
from services.auth import Principal
from services import provider_key_store


class _Snapshot:
    def __init__(self, payload: dict | None) -> None:
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict | None:
        return self._payload


class _Document:
    def __init__(self, documents: dict[str, dict], document_id: str) -> None:
        self._documents = documents
        self._document_id = document_id

    def get(self) -> _Snapshot:
        return _Snapshot(self._documents.get(self._document_id))

    def set(self, payload: dict, merge: bool = False) -> None:
        current = dict(self._documents.get(self._document_id) or {}) if merge else {}
        for key, value in payload.items():
            if merge and isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key] = {**current[key], **value}
            else:
                current[key] = value
        self._documents[self._document_id] = current

    def delete(self) -> None:
        self._documents.pop(self._document_id, None)


class _Collection:
    def __init__(self, documents: dict[str, dict]) -> None:
        self._documents = documents

    def document(self, document_id: str) -> _Document:
        return _Document(self._documents, document_id)


class _Firestore:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def collection(self, _name: str) -> _Collection:
        return _Collection(self.documents)


def test_account_provider_keys_are_encrypted_bound_and_clearable(monkeypatch) -> None:
    original_key = config.settings.byok_encryption_key
    firestore = _Firestore()
    object.__setattr__(
        config.settings,
        "byok_encryption_key",
        Fernet.generate_key().decode("ascii"),
    )
    monkeypatch.setattr(provider_key_store.job_store, "_get_firestore", lambda: firestore)
    try:
        first = provider_key_store.store_provider_keys(
            "owner-one",
            {"meshy": "meshy-secret-123456789"},
        )
        second = provider_key_store.store_provider_keys(
            "owner-one",
            {"tripo": "tsk_secret_123456789"},
        )

        serialized = json.dumps(firestore.documents, default=str)
        assert "meshy-secret-123456789" not in serialized
        assert "tsk_secret_123456789" not in serialized
        assert first["meshy"] is True
        assert second["meshy"] is True
        assert second["tripo"] is True
        assert provider_key_store.load_provider_keys("owner-one") == {
            "meshy": "meshy-secret-123456789",
            "tripo": "tsk_secret_123456789",
        }
        assert provider_key_store.load_provider_keys("owner-two") == {}

        owner_one_document = next(iter(firestore.documents.values()))
        owner_two_id = provider_key_store._document_id("owner-two")
        firestore.documents[owner_two_id] = owner_one_document
        assert provider_key_store.load_provider_keys("owner-two") == {}

        provider_key_store.clear_provider_keys("owner-one")
        assert provider_key_store.load_provider_keys("owner-one") == {}
    finally:
        object.__setattr__(config.settings, "byok_encryption_key", original_key)


def test_request_uses_stored_key_only_for_authenticated_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.provider_key_store,
        "load_provider_keys",
        lambda owner_id: {"meshy": "stored-meshy-123456789"} if owner_id == "owner-one" else {},
    )
    request = Request({"type": "http", "method": "POST", "path": "/generate", "headers": []})
    request.state.principal = Principal(subject="owner-one", email="owner@example.com")

    assert app_module._request_provider_key(request, app_module._MESHY_BYOK_HEADER) == (
        "stored-meshy-123456789"
    )
    assert "stored-meshy-123456789" not in repr(request.state.principal)


def test_explicit_request_key_overrides_stored_key(monkeypatch) -> None:
    monkeypatch.setattr(
        app_module.provider_key_store,
        "load_provider_keys",
        lambda _owner_id: {"meshy": "stored-meshy-123456789"},
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/generate",
            "headers": [(b"x-pulsai-meshy-key", b"draft-meshy-123456789")],
        }
    )
    request.state.principal = Principal(subject="owner-one")

    assert app_module._request_provider_key(request, app_module._MESHY_BYOK_HEADER) == (
        "draft-meshy-123456789"
    )


def test_provider_key_api_saves_presence_without_returning_secrets(monkeypatch) -> None:
    original_required = config.settings.auth_required
    original_client_id = config.settings.google_oauth_client_id
    captured: dict[str, str] = {}
    object.__setattr__(config.settings, "auth_required", True)
    object.__setattr__(
        config.settings,
        "google_oauth_client_id",
        "client.apps.googleusercontent.com",
    )
    monkeypatch.setattr(
        app_module,
        "verify_google_credential",
        lambda token, _audience: Principal(subject=token, email=f"{token}@example.com"),
    )
    monkeypatch.setattr(
        app_module.provider_key_store,
        "persistence_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        app_module.provider_key_store,
        "provider_key_presence",
        lambda _owner_id: {provider: provider == "meshy" for provider in provider_key_store.PROVIDERS},
    )

    def _store(owner_id: str, updates: dict[str, str]) -> dict[str, bool]:
        assert owner_id == "owner-one"
        captured.update(updates)
        return {provider: provider in captured for provider in provider_key_store.PROVIDERS}

    monkeypatch.setattr(app_module.provider_key_store, "store_provider_keys", _store)
    monkeypatch.setattr(
        app_module.provider_key_store,
        "load_provider_keys",
        lambda _owner_id: dict(captured),
    )
    monkeypatch.setattr(app_module.provider_key_store, "clear_provider_keys", lambda _owner_id: captured.clear())
    try:
        with TestClient(app_module.app) as client:
            headers = {"authorization": "Bearer owner-one"}
            saved = client.patch(
                "/account/provider-keys",
                headers=headers,
                json={"keys": {"meshy": "meshy-secret-123456789"}},
            )
            settings_response = client.get("/account/ai-settings", headers=headers)
            invalid = client.patch(
                "/account/provider-keys",
                headers=headers,
                json={"keys": {"meshy": "short"}},
            )
            cleared = client.delete("/account/provider-keys", headers=headers)

        assert saved.status_code == 200
        assert saved.json()["stored_keys"]["meshy"] is True
        assert "meshy-secret-123456789" not in saved.text
        assert settings_response.status_code == 200
        assert settings_response.json()["keys_persisted"] is True
        assert settings_response.json()["stored_keys"]["meshy"] is True
        assert "meshy-secret-123456789" not in settings_response.text
        assert invalid.status_code == 400
        assert cleared.status_code == 204
        assert captured == {}
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "google_oauth_client_id", original_client_id)
