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


def test_public_safe_mode_hides_legacy_compute_route() -> None:
    original_required = config.settings.auth_required
    original_dev = config.settings.insecure_local_dev
    original_safe = config.settings.public_safe_mode
    object.__setattr__(config.settings, "auth_required", False)
    object.__setattr__(config.settings, "insecure_local_dev", True)
    object.__setattr__(config.settings, "public_safe_mode", True)
    try:
        with TestClient(app_module.app) as client:
            assert client.post("/process-model", json={"glb_url": "http://127.0.0.1"}).status_code == 404
            assert client.post("/preview-useful", json={}).status_code == 404
            assert client.post("/build-useful", json={}).status_code == 404
            assert client.post("/import-model").status_code == 404
            assert client.get("/projects").status_code == 404
            assert client.post("/workspace/create", json={}).status_code == 404
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
