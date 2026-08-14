from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
import config
from services.auth import Principal, reset_current_principal, set_current_principal
from services.codegen.engine import trusted_script_metadata
from services.codegen.models import DesignParameter, NamedFeature
from services.codegen.store import create_design


def test_google_auth_blocks_anonymous_and_cross_owner_access(tmp_path, monkeypatch) -> None:
    original_output = config.settings.output_dir
    original_artifacts_path = app_module.artifacts_path
    original_required = config.settings.auth_required
    original_client_id = config.settings.google_oauth_client_id
    object.__setattr__(config.settings, "output_dir", tmp_path)
    app_module.artifacts_path = tmp_path
    object.__setattr__(config.settings, "auth_required", True)
    object.__setattr__(config.settings, "google_oauth_client_id", "client.apps.googleusercontent.com")
    monkeypatch.setattr(
        app_module,
        "verify_google_credential",
        lambda token, audience: Principal(subject=token, email=f"{token}@example.com"),
    )
    monkeypatch.setattr("services.codegen.cloud_store.save_design_payload", lambda *_: None)
    monkeypatch.setattr("services.codegen.cloud_store.load_design_payload", lambda *_: None)
    monkeypatch.setattr("services.codegen.cloud_store.list_design_payloads", lambda: [])
    monkeypatch.setattr("services.codegen.cloud_store.load_build_payload", lambda *_: None)
    try:
        context = set_current_principal(Principal(subject="owner-one"))
        try:
            design = create_design(
                name="Private part",
                script="result = Box(1, 1, 1)",
                parameters=[DesignParameter(name="width", value=1.0)],
                features=[NamedFeature(name="body", source="Box(1, 1, 1)")],
                metadata=trusted_script_metadata("result = Box(1, 1, 1)"),
            )
        finally:
            reset_current_principal(context)

        with TestClient(app_module.app) as client:
            session = client.post(
                "/auth/session", headers={"authorization": "Bearer owner-one"}
            )
            assert session.status_code == 204
            assert "HttpOnly" in session.headers["set-cookie"]
            assert "SameSite=none" in session.headers["set-cookie"]
            client.cookies.clear()
            assert client.get(f"/design/{design.id}").status_code == 401
            owner_response = client.get(
                f"/design/{design.id}", headers={"authorization": "Bearer owner-one"}
            )
            assert owner_response.status_code == 200
            glb_url = owner_response.json()["latest_build"]["artifacts"]["glb"]["url"]
            artifact_head = client.head(
                glb_url, headers={"authorization": "Bearer owner-one"}
            )
            assert artifact_head.status_code == 200
            assert artifact_head.content == b""
            assert client.get(
                f"/design/{design.id}", headers={"authorization": "Bearer owner-two"}
            ).status_code == 404
            assert client.get(
                f"/cloud-artifacts/three-d/designs/{design.id}/model.glb",
                headers={"authorization": "Bearer owner-two"},
            ).status_code == 404
            other_list = client.get("/design", headers={"authorization": "Bearer owner-two"})
            assert other_list.status_code == 200
            assert other_list.json()["designs"] == []
    finally:
        object.__setattr__(config.settings, "output_dir", original_output)
        app_module.artifacts_path = original_artifacts_path
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "google_oauth_client_id", original_client_id)
