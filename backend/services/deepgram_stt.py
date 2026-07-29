from __future__ import annotations

from typing import Optional

import httpx

from config import settings


def _extract_transcript(payload: dict) -> Optional[str]:
    results = payload.get("results") or {}
    channels = results.get("channels") or []
    if not channels:
        return None
    alternatives = channels[0].get("alternatives") or []
    if not alternatives:
        return None
    transcript = alternatives[0].get("transcript")
    if isinstance(transcript, str) and transcript.strip():
        return transcript.strip()
    return None


SUPPORTED_LANGUAGES = {"pl", "en", "multi"}
CAD_VOCABULARY = [
    "Pulsai",
    "CAD",
    "STL",
    "STEP",
    "GLB",
    "druk 3D",
    "średnica",
    "promień",
    "wysokość",
    "głębokość",
    "otwór",
    "fazowanie",
    "zaokrąglenie",
]


def _request_params(*, model: str, language: str) -> dict[str, str | list[str]]:
    """Build a Deepgram request using only features supported by the model/language."""
    language_hint = language if language in SUPPORTED_LANGUAGES else "pl"
    normalized_model = model.strip().lower()
    params: dict[str, str | list[str]] = {
        "model": model,
        "language": language_hint,
        "punctuate": "true",
        "smart_format": "true",
        "numerals": "true",
    }

    # Deepgram keyterm prompting is Nova-3-only. Nova-2 uses the legacy
    # keywords parameter instead. Measurements are currently English-only.
    if normalized_model.startswith("nova-3"):
        params["keyterm"] = CAD_VOCABULARY
    else:
        params["keywords"] = [f"{term}:2" for term in CAD_VOCABULARY[:5]]
    if language_hint == "en":
        params["measurements"] = "true"
    return params


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    content_type: str,
    language: str = "pl",
) -> str:
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY is not set")

    url = f"{settings.deepgram_base_url}/v1/listen"
    params = _request_params(model=settings.deepgram_model, language=language)
    headers = {
        "Authorization": f"Token {settings.deepgram_api_key}",
        "Content-Type": content_type or "application/octet-stream",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, params=params, content=audio_bytes, headers=headers)
        response.raise_for_status()
        payload = response.json()

    transcript = _extract_transcript(payload)
    if not transcript:
        raise RuntimeError("Deepgram returned empty transcript")
    return transcript
