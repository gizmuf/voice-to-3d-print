from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional

import httpx

from config import settings

SYSTEM_PROMPT = (
    "You extract concise 3D generation prompts from user speech. "
    "Return ONLY JSON with a single key 'prompt'. "
    "No markdown, no extra text."
)

IMAGE_SYSTEM_PROMPT = (
    "You are given a reference image for a printable CAD design. "
    "Describe only visible geometry, proportions, repeated features, joints, and likely functional surfaces. "
    "Do not invent hidden mechanisms or exact dimensions. Mark uncertain details as uncertain and mention "
    "the most important missing measurement. Write the prompt in Polish. "
    "Return ONLY JSON with a single key 'prompt'. "
    "No markdown, no extra text."
)


@dataclass(frozen=True)
class GeminiPromptResult:
    prompt: str | None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * 0.30 + self.output_tokens * 2.50) / 1_000_000


async def _generate(payload: dict) -> tuple[str | None, dict]:
    async with httpx.AsyncClient(timeout=90) as client:
        if settings.gemini_api_key:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent",
                params={"key": settings.gemini_api_key},
                json={"contents": payload["contents"]},
            )
            response.raise_for_status()
            data = response.json()
            parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
            return text or None, data.get("usageMetadata") or {}

        response = await client.post(settings.gemini_proxy_url, json=payload)
        response.raise_for_status()
        data = response.json()
        text = data.get("text") if isinstance(data, dict) else None
        return text, data.get("usageMetadata") or {} if isinstance(data, dict) else {}


def _parse_prompt(text: str | None) -> Optional[str]:
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
    return text.strip() or None


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

    text, _ = await _generate(payload)
    return _parse_prompt(text)


async def extract_prompt_from_image(
    content: bytes,
    content_type: str,
) -> Optional[str]:
    return (await extract_prompt_from_image_with_usage(content, content_type)).prompt


async def extract_prompt_from_image_with_usage(
    content: bytes,
    content_type: str,
) -> GeminiPromptResult:
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

    text, usage = await _generate(payload)
    return GeminiPromptResult(
        prompt=_parse_prompt(text),
        input_tokens=int(usage.get("promptTokenCount") or 0),
        output_tokens=int(usage.get("candidatesTokenCount") or 0),
    )
