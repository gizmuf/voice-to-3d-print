from __future__ import annotations

import asyncio

import pytest

import config
from services.deepgram_stt import transcribe_audio
from services.gemini_intent import extract_prompt_from_image_with_usage
from services.generation import generate_model
from services.jewelry_trace import generate_jewelry_concepts


@pytest.fixture(autouse=True)
def _restore_settings():
    original_spend = config.settings.allow_platform_ai_spend
    original_meshy_key = config.settings.meshy_api_key
    try:
        yield
    finally:
        object.__setattr__(config.settings, "allow_platform_ai_spend", original_spend)
        object.__setattr__(config.settings, "meshy_api_key", original_meshy_key)


def test_paid_mesh_provider_is_blocked_before_network() -> None:
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)
    object.__setattr__(config.settings, "meshy_api_key", "configured-but-forbidden")

    with pytest.raises(ValueError, match="Platform-paid Meshy"):
        asyncio.run(generate_model("a bracket", provider="meshy"))


def test_paid_image_intent_is_blocked_before_network() -> None:
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)

    with pytest.raises(ValueError, match="Platform-paid Gemini"):
        asyncio.run(extract_prompt_from_image_with_usage(b"image", "image/png"))


def test_paid_stt_is_blocked_before_network() -> None:
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)

    with pytest.raises(ValueError, match="Platform-paid Deepgram"):
        asyncio.run(transcribe_audio(b"audio", content_type="audio/webm"))


def test_paid_concept_generation_returns_disabled_without_network() -> None:
    object.__setattr__(config.settings, "allow_platform_ai_spend", False)

    result = asyncio.run(generate_jewelry_concepts(prompt="a pendant"))

    assert result["configured"] is False
    assert result["concepts"] == []
