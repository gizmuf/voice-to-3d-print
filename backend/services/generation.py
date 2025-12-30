from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from config import settings


@dataclass
class GenerationResult:
    provider: str
    task_id: str
    status: str
    glb_url: str
    raw: Dict[str, Any]


def _extract_glb_url(payload: Dict[str, Any]) -> Optional[str]:
    for key in ("glb_url", "glb", "model_url"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    model_urls = payload.get("model_urls") or payload.get("modelUrls")
    if isinstance(model_urls, dict):
        for key in ("glb", "glb_url", "model", "url"):
            value = model_urls.get(key)
            if isinstance(value, str) and value:
                return value
    return None


async def generate_model(prompt: str, *, provider: Optional[str] = None) -> GenerationResult:
    provider = (provider or settings.threed_provider).lower()
    if provider == "meshy":
        return await _generate_meshy(prompt)
    if provider == "tripo":
        return await _generate_tripo(prompt)
    raise ValueError(f"Unsupported provider: {provider}")


async def _generate_meshy(prompt: str) -> GenerationResult:
    if not settings.meshy_api_key:
        raise ValueError("MESHY_API_KEY is required for Meshy generation")

    url = f"{settings.meshy_base_url}{settings.meshy_create_endpoint}"
    headers = {"Authorization": f"Bearer {settings.meshy_api_key}"}
    payload = {
        "prompt": prompt,
        "art_style": "realistic",
        "mode": "preview",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    task_id = data.get("result") or data.get("id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Meshy response missing task id: {data}")

    status_url = f"{settings.meshy_base_url}{settings.meshy_status_endpoint}".format(task_id=task_id)
    return await _poll_generation(
        provider="meshy",
        task_id=str(task_id),
        status_url=status_url,
        headers=headers,
    )


async def _generate_tripo(prompt: str) -> GenerationResult:
    if not settings.tripo_api_key:
        raise ValueError("TRIPO_API_KEY is required for Tripo generation")

    url = f"{settings.tripo_base_url}{settings.tripo_create_endpoint}"
    headers = {"Authorization": f"Bearer {settings.tripo_api_key}"}
    payload = {
        "type": "text-to-3d",
        "prompt": prompt,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    task_id = data.get("task_id") or data.get("id") or data.get("result")
    if not task_id:
        raise RuntimeError(f"Tripo response missing task id: {data}")

    status_url = f"{settings.tripo_base_url}{settings.tripo_status_endpoint}".format(task_id=task_id)
    return await _poll_generation(
        provider="tripo",
        task_id=str(task_id),
        status_url=status_url,
        headers=headers,
    )


async def _poll_generation(
    *,
    provider: str,
    task_id: str,
    status_url: str,
    headers: Dict[str, str],
    timeout_s: int = 900,
    poll_interval_s: float = 3.0,
) -> GenerationResult:
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            response = await client.get(status_url, headers=headers)
            response.raise_for_status()
            data = response.json()

            status = (data.get("status") or data.get("state") or "").lower()
            glb_url = _extract_glb_url(data) or _extract_glb_url(data.get("result", {}))
            if status in {"succeeded", "completed", "success"} and glb_url:
                return GenerationResult(
                    provider=provider,
                    task_id=task_id,
                    status=status,
                    glb_url=glb_url,
                    raw=data,
                )

            if status in {"failed", "error", "canceled"}:
                raise RuntimeError(f"{provider} generation failed: {data}")

            if time.monotonic() - start > timeout_s:
                raise TimeoutError(f"{provider} generation timed out after {timeout_s}s")

            await asyncio.sleep(poll_interval_s)
