from __future__ import annotations

import pytest
import asyncio

from services.integrations import onshape
from services.integrations.onshape import OnshapeClient, OnshapeError, OnshapeLocation, parse_onshape_url


def test_parse_onshape_workspace_url() -> None:
    location = parse_onshape_url(
        "https://cad.onshape.com/documents/d/doc123/w/work456/e/elem789"
    )

    assert location.document_id == "doc123"
    assert location.wvm == "w"
    assert location.wvm_id == "work456"
    assert location.element_id == "elem789"


def test_parse_onshape_version_url() -> None:
    location = parse_onshape_url(
        "https://cad.onshape.com/documents/d/doc123/v/ver456/e/elem789"
    )

    assert location.wvm == "v"
    assert location.wvm_id == "ver456"


def test_parse_requires_workspace_or_version() -> None:
    with pytest.raises(OnshapeError):
        parse_onshape_url("https://cad.onshape.com/documents/d/doc123/e/elem789")


def test_export_step_downloads_result_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_json_url(self, method: str, url: str, **kwargs):
        calls.append((method, url))
        if url.endswith("/export/step"):
            assert kwargs["json"]["storeInDocument"] is True
            return {"requestState": "ACTIVE", "href": "https://cad.onshape.com/api/v10/translations/t1"}
        if url.endswith("/translations/t1"):
            return {
                "requestState": "DONE",
                "resultElementIds": ["blob123"],
            }
        raise AssertionError(url)

    async def fake_bytes(self, method: str, path: str, **kwargs):
        calls.append((method, path))
        assert path.endswith("/blobelements/d/doc123/w/work456/e/blob123")
        return b"STEP-DATA"

    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(OnshapeClient, "_request_json_url", fake_json_url)
    monkeypatch.setattr(OnshapeClient, "_request_bytes", fake_bytes)
    monkeypatch.setattr(onshape, "_sleep", no_sleep)

    client = OnshapeClient(auth=onshape.OnshapeAuth(mode="oauth", access_token="token"))
    async def run() -> tuple[bytes, str]:
        return await client.export_step(
            OnshapeLocation(
                document_id="doc123",
                wvm="w",
                wvm_id="work456",
                element_id="elem789",
            )
        )

    content, filename = asyncio.run(run())

    assert content == b"STEP-DATA"
    assert filename == "onshape-doc123-elem789.step"
    assert calls[0][1].endswith("/partstudios/d/doc123/w/work456/e/elem789/export/step")
