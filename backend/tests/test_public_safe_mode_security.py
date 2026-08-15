from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app as app_module
import config
from services.codegen.ast_audit import audit_script
from services.codegen.engine import (
    DesignBuildError,
    audit_then_run,
    design_script_is_trusted,
    trusted_script_metadata,
)
from services.codegen.sandbox import _run_bounded
from services.step_import import import_step_reference
from slicer_service import process_model


def test_untrusted_cad_python_is_rejected_before_runner(monkeypatch) -> None:
    object.__setattr__(config.settings, "allow_untrusted_cad_code", False)
    called = False

    def forbidden_runner(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("services.codegen.engine.run_design", forbidden_runner)
    with pytest.raises(DesignBuildError, match="Untrusted Python"):
        audit_then_run(script="result = Box(1, 1, 1)")
    assert called is False


def test_ast_rejects_string_reflection_bypass() -> None:
    result = audit_script(
        'builtins = getattr(lambda: None, "__globals__")["__builtins__"]\n'
        "result = Box(1, 1, 1)"
    )
    assert result.ok is False
    assert any("getattr" in error or "dunder strings" in error for error in result.errors)


def test_trusted_script_digest_is_bound_to_exact_source() -> None:
    script = "result = Box(1, 1, 1)"
    design = SimpleNamespace(script=script, metadata=trusted_script_metadata(script))
    assert design_script_is_trusted(design) is True
    design.script = "result = Box(2, 2, 2)"
    assert design_script_is_trusted(design) is False


def test_sandbox_timeout_survives_closed_output_pipes(tmp_path: Path) -> None:
    started = time.monotonic()
    _, _, _, timed_out, _ = _run_bounded(
        [
            sys.executable,
            "-c",
            "import os,time; os.close(1); os.close(2); time.sleep(5)",
        ],
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout_s=0.2,
        output_limit=1024,
    )
    assert timed_out is True
    assert time.monotonic() - started < 2.0


def test_remote_model_url_is_rejected(tmp_path: Path) -> None:
    original_output = config.settings.output_dir
    object.__setattr__(config.settings, "output_dir", tmp_path)
    try:
        with pytest.raises(ValueError, match="Remote model URLs"):
            process_model("http://169.254.169.254/latest/meta-data", "a" * 32)
    finally:
        object.__setattr__(config.settings, "output_dir", original_output)


def test_step_upload_filename_cannot_escape_output(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class Imported:
        pass

    monkeypatch.setattr(
        "services.step_import.cq_importers.importStep",
        lambda path: (captured.setdefault("path", path), Imported())[1],
    )
    monkeypatch.setattr("services.step_import.cq_exporters.export", lambda *_: None)
    monkeypatch.setattr(
        "services.step_import.trimesh.load_mesh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("stop")),
    )

    with pytest.raises(RuntimeError, match="stop"):
        import_step_reference(b"STEP", "../../outside.step", tmp_path)
    assert Path(captured["path"]) == tmp_path / "source.step"
    assert not (tmp_path.parent / "outside.step").exists()


def test_public_safe_mode_hides_legacy_compute_routes_but_admits_owned_mesh_flow() -> None:
    original_required = config.settings.auth_required
    original_dev = config.settings.insecure_local_dev
    original_safe = config.settings.public_safe_mode
    object.__setattr__(config.settings, "auth_required", False)
    object.__setattr__(config.settings, "insecure_local_dev", True)
    object.__setattr__(config.settings, "public_safe_mode", True)
    try:
        with TestClient(app_module.app) as client:
            process_response = client.post("/process-model", json={"glb_url": "http://127.0.0.1"})
            assert process_response.status_code == 400
            assert "owned generation job" in process_response.json()["detail"]
            assert client.post("/generate", json={"prompt": "a figure", "provider": "meshy"}).status_code == 422
            assert client.post("/preview-useful", json={}).status_code == 404
            assert client.post("/build-useful", json={}).status_code == 404
            assert client.post("/import-model").status_code == 404
            assert client.get("/projects").status_code == 404
            assert client.post("/workspace/create", json={}).status_code == 404
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "insecure_local_dev", original_dev)
        object.__setattr__(config.settings, "public_safe_mode", original_safe)


def test_public_safe_mode_rejects_process_source_not_bound_to_owned_job(monkeypatch) -> None:
    original_required = config.settings.auth_required
    original_dev = config.settings.insecure_local_dev
    original_safe = config.settings.public_safe_mode
    object.__setattr__(config.settings, "auth_required", False)
    object.__setattr__(config.settings, "insecure_local_dev", True)
    object.__setattr__(config.settings, "public_safe_mode", True)
    called = False

    def forbidden_process(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        app_module,
        "get_job",
        lambda _job_id: {
            "generation": {"glb_source_url": "/cloud-artifacts/three-d/jobs/" + "a" * 32 + "/provider-source.glb"}
        },
    )
    monkeypatch.setattr(app_module, "process_model", forbidden_process)
    try:
        with TestClient(app_module.app) as client:
            response = client.post(
                "/process-model",
                json={"job_id": "a" * 32, "glb_url": "https://attacker.example/model.glb"},
            )
        assert response.status_code == 400
        assert called is False
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "insecure_local_dev", original_dev)
        object.__setattr__(config.settings, "public_safe_mode", original_safe)


def test_public_safe_mode_persists_provider_output_as_owned_artifact(monkeypatch) -> None:
    original_required = config.settings.auth_required
    original_dev = config.settings.insecure_local_dev
    original_safe = config.settings.public_safe_mode
    object.__setattr__(config.settings, "auth_required", False)
    object.__setattr__(config.settings, "insecure_local_dev", True)
    object.__setattr__(config.settings, "public_safe_mode", True)
    updates: list[dict] = []

    async def fake_generate(*_args, **_kwargs):
        return app_module.GenerationResult(
            provider="meshy",
            task_id="provider-task",
            status="completed",
            glb_url="https://provider.example/signed-model.glb",
            raw={},
        )

    async def fake_persist(job_id: str, provider_url: str) -> str:
        assert len(job_id) == 32
        assert provider_url == "https://provider.example/signed-model.glb"
        return f"/cloud-artifacts/three-d/jobs/{job_id}/provider-source.glb"

    monkeypatch.setattr(app_module, "_request_provider_key", lambda *_args: "customer-key-123456")
    monkeypatch.setattr(app_module, "ensure_job", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_job_belongs_to", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(app_module, "generate_model", fake_generate)
    monkeypatch.setattr(app_module, "_persist_provider_glb", fake_persist)
    monkeypatch.setattr(app_module, "update_job", lambda _job_id, payload: updates.append(payload))
    monkeypatch.setattr(
        app_module,
        "get_job",
        lambda _job_id: {
            "generation": {"glb_source_url": updates[-1]["generation.glb_source_url"]}
        } if updates else None,
    )
    try:
        with TestClient(app_module.app) as client:
            response = client.post(
                "/generate",
                json={"prompt": "a figure", "provider": "meshy", "job_id": "b" * 32},
            )
        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"] != "b" * 32
        assert payload["glb_url"].startswith("/cloud-artifacts/three-d/jobs/")
        assert updates[-1]["generation.glb_source_url"] == payload["glb_url"]
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "insecure_local_dev", original_dev)
        object.__setattr__(config.settings, "public_safe_mode", original_safe)


def test_cookie_cannot_authorize_unsafe_method(monkeypatch) -> None:
    original_required = config.settings.auth_required
    original_client = config.settings.google_oauth_client_id
    object.__setattr__(config.settings, "auth_required", True)
    object.__setattr__(config.settings, "google_oauth_client_id", "client.apps.googleusercontent.com")
    monkeypatch.setattr(
        app_module,
        "verify_google_credential",
        lambda token, audience: app_module.Principal(subject=token),
    )
    try:
        with TestClient(app_module.app) as client:
            client.cookies.set("pulsai_google_id", "owner-one")
            response = client.post("/design/create", json={"template_id": "box"})
            assert response.status_code == 401
    finally:
        object.__setattr__(config.settings, "auth_required", original_required)
        object.__setattr__(config.settings, "google_oauth_client_id", original_client)


def test_upload_reader_stops_at_limit() -> None:
    class Upload:
        def __init__(self) -> None:
            self.data = bytearray(b"x" * 12)

        async def read(self, size: int) -> bytes:
            chunk = bytes(self.data[:size])
            del self.data[:size]
            return chunk

    with pytest.raises(app_module.HTTPException) as exc:
        asyncio.run(app_module._read_upload_limited(Upload(), 10))
    assert exc.value.status_code == 413
