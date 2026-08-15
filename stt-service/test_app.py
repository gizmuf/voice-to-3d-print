from __future__ import annotations

from fastapi.testclient import TestClient

import app as stt_app


def test_health_remains_public_and_reports_platform_spend_gate() -> None:
    response = TestClient(stt_app.app).get("/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["platform_ai_spend_enabled"] is False


def test_stt_rejects_unauthenticated_multipart_before_parsing() -> None:
    response = TestClient(stt_app.app).post(
        "/stt",
        files={"audio": ("sample.webm", b"not-real-audio", "audio/webm")},
        data={"language": "pl"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "STT service authentication required."}
