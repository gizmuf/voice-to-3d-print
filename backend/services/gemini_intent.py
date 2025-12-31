from __future__ import annotations

import base64
import json
from typing import Optional

import httpx

from config import settings

SYSTEM_PROMPT = (
    "You extract concise 3D generation prompts from user speech. "
    "Return ONLY JSON with a single key 'prompt'. "
    "No markdown, no extra text."
)

IMAGE_SYSTEM_PROMPT = (
    "You are given an image. Describe the object as a concise 3D generation prompt. "
    "Focus on shape, proportions, and key features. "
    "Return ONLY JSON with a single key 'prompt'. "
    "No markdown, no extra text."
)


async def extract_prompt(user_text: str) -> Optional[str]:
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"{SYSTEM_PROMPT}\nUser: {user_text}",
                    }
                ],
            }
        ],
        "modelName": settings.gemini_model,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(settings.gemini_proxy_url, json=payload)
        response.raise_for_status()
        data = response.json()

    text = data.get("text") if isinstance(data, dict) else None
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            prompt = parsed.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()
    return cleaned or None


async def extract_prompt_from_image(
    content: bytes,
    content_type: str,
) -> Optional[str]:
    encoded = base64.b64encode(content).decode("ascii")
    mime_type = content_type or "image/jpeg"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": IMAGE_SYSTEM_PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": encoded}},
                ],
            }
        ],
        "modelName": settings.gemini_model,
    }

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(settings.gemini_proxy_url, json=payload)
        response.raise_for_status()
        data = response.json()

    text = data.get("text") if isinstance(data, dict) else None
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            prompt = parsed.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()
    return cleaned or None
