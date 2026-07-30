from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from services import gemini_intent


def test_image_intent_accepts_design_id_for_cost_ledger() -> None:
    from app import image_intent

    assert "design_id" in inspect.signature(image_intent).parameters


def test_image_prompt_uses_direct_usage_metadata(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "candidates": [
                    {"content": {"parts": [{"text": '{"prompt":"Kołowrotek z widocznymi szczebelkami."}'}]}}
                ],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
            }

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            assert "gemini-3.5-flash-lite:generateContent" in url
            assert kwargs["params"] == {"key": "test-key"}
            return Response()

    monkeypatch.setattr(gemini_intent.httpx, "AsyncClient", Client)
    monkeypatch.setattr(
        gemini_intent,
        "settings",
        SimpleNamespace(
            gemini_api_key="test-key",
            gemini_model="gemini-3.5-flash-lite",
            gemini_proxy_url="https://proxy.invalid",
        ),
    )

    result = asyncio.run(gemini_intent.extract_prompt_from_image_with_usage(b"png", "image/png"))

    assert result.prompt == "Kołowrotek z widocznymi szczebelkami."
    assert result.input_tokens == 100
    assert result.output_tokens == 20
    assert result.cost_usd == (100 * 0.30 + 20 * 2.50) / 1_000_000
