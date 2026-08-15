from __future__ import annotations

import asyncio

import config
import pytest
from services import generation
from services.useful_objects import route_mode


@pytest.fixture(autouse=True)
def _restore_spend_setting():
    original = config.settings.allow_platform_ai_spend
    try:
        yield
    finally:
        object.__setattr__(config.settings, "allow_platform_ai_spend", original)


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_meshy_byok_bypasses_platform_spend_and_uses_quality_payload(monkeypatch) -> None:
    captured: dict = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json, headers):
            captured.update(url=url, payload=json, headers=headers)
            return _Response({"result": "task-1"})

    async def poll(**kwargs):
        captured["poll"] = kwargs
        return generation.GenerationResult("meshy", "task-1", "completed", "https://example/model.glb", {})

    monkeypatch.setattr(generation.httpx, "AsyncClient", Client)
    monkeypatch.setattr(generation, "_poll_generation", poll)
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)

    result = asyncio.run(generation.generate_model(
        "a figurine", provider="meshy", api_key="customer-meshy-secret", quality_tier="quality"
    ))

    assert result.provider == "meshy"
    assert captured["headers"] == {"Authorization": "Bearer customer-meshy-secret"}
    assert captured["payload"]["ai_model"] == "meshy-6"
    assert captured["payload"]["target_polycount"] == 150_000


def test_tripo_reads_nested_task_id_and_draft_model(monkeypatch) -> None:
    captured: dict = {}

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, *, json, headers):
            captured.update(payload=json, headers=headers)
            return _Response({"code": 0, "data": {"task_id": "nested-task"}})

    async def poll(**kwargs):
        captured["poll"] = kwargs
        return generation.GenerationResult("tripo", kwargs["task_id"], "completed", "https://example/model.glb", {})

    monkeypatch.setattr(generation.httpx, "AsyncClient", Client)
    monkeypatch.setattr(generation, "_poll_generation", poll)
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)

    result = asyncio.run(generation.generate_model(
        "a pilot", provider="tripo", api_key="customer-tripo-secret", quality_tier="draft"
    ))

    assert result.task_id == "nested-task"
    assert captured["payload"]["model_version"] == "P1-20260311"
    assert captured["payload"]["texture"] is False


def test_auto_routing_prefers_tripo_for_figures_and_requires_a_key() -> None:
    assert generation.select_mesh_provider(
        "figurka motoparalotniarza", "auto", meshy_available=True, tripo_available=True
    ) == "tripo"
    assert generation.select_mesh_provider(
        "decorative vase", "auto", meshy_available=True, tripo_available=True
    ) == "meshy"
    assert route_mode("figurka motoparalotniarza")["mode"] == "creative"
