from __future__ import annotations

from fastapi.testclient import TestClient

import app as app_module
import config
from services.auth import Principal, reset_current_principal, set_current_principal
from services.codegen.engine import trusted_script_metadata
from services.codegen.models import DesignParameter, NamedFeature
from services.codegen.store import create_design
from services.editable_model import BodyNode, EditableModel
from services.workspace import create_workspace


def test_anthropic_platform_access_is_limited_to_allowlisted_google_email(
    monkeypatch,
) -> None:
    original_required = config.settings.auth_required
    original_client_id = config.settings.google_oauth_client_id
    original_spend = config.settings.allow_platform_ai_spend
    original_key = config.settings.anthropic_api_key
    original_allowlist = config.settings.anthropic_platform_email_allowlist
    object.__setattr__(config.settings, "auth_required", True)
    object.__setattr__(
        config.settings,
        "google_oauth_client_id",
        "client.apps.googleusercontent.com",
    )
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)
    object.__setattr__(config.settings, "anthropic_api_key", "sk-ant-platform")
    object.__setattr__(
        config.settings,
        "anthropic_platform_email_allowlist",
        frozenset({"olga@example.com"}),
    )
    monkeypatch.setattr(
        app_module,
        "verify_google_credential",
        lambda token, audience: Principal(subject=token, email=token),
    )
    try:
        with TestClient(app_module.app) as client:
            allowed = client.get(
                "/account/ai-settings",
                headers={"authorization": "Bearer Olga@Example.com"},
            )
            denied = client.get(
                "/account/ai-settings",
                headers={"authorization": "Bearer stranger@example.com"},
            )

        assert allowed.status_code == 200
        assert allowed.json()["anthropic"]["platform_access"] is True
        assert allowed.json()["anthropic"]["billing_source"] == "platform"
        assert allowed.json()["keys_persisted"] is False
        assert "sk-ant-platform" not in allowed.text
        assert denied.status_code == 200
        assert denied.json()["anthropic"]["platform_access"] is False
        assert denied.json()["anthropic"]["billing_source"] == "customer_byok"
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "google_oauth_client_id", original_client_id)
        object.__setattr__(config.settings, "allow_platform_ai_spend", original_spend)
        object.__setattr__(config.settings, "anthropic_api_key", original_key)
        object.__setattr__(
            config.settings,
            "anthropic_platform_email_allowlist",
            original_allowlist,
        )


def test_google_auth_blocks_anonymous_and_cross_owner_access(tmp_path, monkeypatch) -> None:
    original_output = config.settings.output_dir
    original_artifacts_path = app_module.artifacts_path
    original_required = config.settings.auth_required
    original_client_id = config.settings.google_oauth_client_id
    original_cors_origins = app_module._cors_origins
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
    app_module._cors_origins = ["https://3d.pulsai.app"]
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
            client.cookies.set("pulsai_google_id", "owner-one")
            assert client.get("/auth/session").json() == {"authenticated": True}
            without_csrf = client.post(
                f"/design/{design.id}/parameter-lock",
                json={"name": "width", "locked": True},
            )
            assert without_csrf.status_code == 401
            restored_session = client.post(
                f"/design/{design.id}/parameter-lock",
                json={"name": "width", "locked": True},
                headers={
                    "origin": "https://3d.pulsai.app",
                    "x-pulsai-csrf": "same-origin",
                },
            )
            assert restored_session.status_code == 200
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
        app_module._cors_origins = original_cors_origins


def test_legacy_workspace_and_job_artifacts_remain_owner_isolated(
    tmp_path, monkeypatch
) -> None:
    original_output = config.settings.output_dir
    original_artifacts_path = app_module.artifacts_path
    original_required = config.settings.auth_required
    original_client_id = config.settings.google_oauth_client_id
    original_safe_mode = config.settings.public_safe_mode
    import services.workspace as workspace_store

    original_workspaces_dir = workspace_store.WORKSPACES_DIR
    object.__setattr__(config.settings, "output_dir", tmp_path)
    object.__setattr__(config.settings, "auth_required", True)
    object.__setattr__(config.settings, "google_oauth_client_id", "client.apps.googleusercontent.com")
    object.__setattr__(config.settings, "public_safe_mode", False)
    app_module.artifacts_path = tmp_path
    workspace_store.WORKSPACES_DIR = tmp_path / "workspaces"
    monkeypatch.setattr(
        app_module,
        "verify_google_credential",
        lambda token, audience: Principal(subject=token, email=f"{token}@example.com"),
    )
    monkeypatch.setattr(app_module, "_get_firestore", lambda: None)

    try:
        context = set_current_principal(Principal(subject="owner-one"))
        try:
            workspace = create_workspace(
                "native",
                EditableModel(
                    id="model-one",
                    source="native",
                    revision_id="revision-one",
                    bodies=[BodyNode(id="body-one", kind="body", label="Body")],
                ),
            )
            workspace_artifact = tmp_path / "workspaces" / workspace.workspace_id / "model.glb"
            workspace_artifact.write_bytes(b"workspace")
            assert app_module._job_belongs_to(workspace.workspace_id, "owner-one") is True
            assert app_module._job_belongs_to(workspace.workspace_id, "owner-two") is False

            job_id = "a" * 32
            job_dir = tmp_path / job_id
            job_dir.mkdir(parents=True)
            (job_dir / "model.glb").write_bytes(b"job")
            (job_dir / "metadata.json").write_text(
                '{"job_id":"' + job_id + '","owner_id":"owner-one"}'
            )
        finally:
            reset_current_principal(context)

        with TestClient(app_module.app) as client:
            owner_headers = {"authorization": "Bearer owner-one"}
            other_headers = {"authorization": "Bearer owner-two"}
            workspace_url = f"/artifacts/workspaces/{workspace.workspace_id}/model.glb"
            job_url = f"/artifacts/{job_id}/model.glb"
            assert client.get(workspace_url, headers=owner_headers).content == b"workspace"
            assert client.get(workspace_url, headers=other_headers).status_code == 404
            assert client.get(job_url, headers=owner_headers).content == b"job"
            assert client.get(job_url, headers=other_headers).status_code == 404
    finally:
        object.__setattr__(config.settings, "output_dir", original_output)
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "google_oauth_client_id", original_client_id)
        object.__setattr__(config.settings, "public_safe_mode", original_safe_mode)
        app_module.artifacts_path = original_artifacts_path
        workspace_store.WORKSPACES_DIR = original_workspaces_dir
