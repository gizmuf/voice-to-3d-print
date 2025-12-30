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


async def transcribe_audio(audio_bytes: bytes, *, content_type: str) -> str:
    if not settings.deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY is not set")

    url = f"{settings.deepgram_base_url}/v1/listen"
    params = {
        "model": settings.deepgram_model,
        "punctuate": "true",
        "smart_format": "true",
    }
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
