from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient


def _load_stt_app(monkeypatch):
    monkeypatch.setenv("PULSAI_STT_INTERNAL_TOKEN", "test-internal-token")
    module_path = Path(__file__).resolve().parents[2] / "stt-service" / "app.py"
    spec = importlib.util.spec_from_file_location("pulsai_stt_security_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stt_rejects_missing_token_before_multipart_parsing(monkeypatch) -> None:
    module = _load_stt_app(monkeypatch)
    with TestClient(module.app) as client:
        response = client.post(
            "/stt",
            content=b"not-even-valid-multipart",
            headers={"content-type": "multipart/form-data; boundary=missing"},
        )
    assert response.status_code == 401


def test_stt_rejects_oversized_body_before_multipart_parsing(monkeypatch) -> None:
    module = _load_stt_app(monkeypatch)
    with TestClient(module.app) as client:
        response = client.post(
            "/stt",
            content=b"not-even-valid-multipart",
            headers={
                "authorization": "Bearer test-internal-token",
                "content-type": "multipart/form-data; boundary=missing",
                "content-length": str(module.MAX_STT_REQUEST_BYTES + 1),
            },
        )
    assert response.status_code == 413
