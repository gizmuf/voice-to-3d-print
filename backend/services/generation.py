from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import httpx

from config import settings
from services.parametric import generate_parametric_model


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
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("pbr_model", "model", "base_model", "glb", "glb_url", "url"):
            value = output.get(key)
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
    if provider == "parametric":
        return _generate_parametric(prompt)
    if provider == "llama-mesh":
        raise ValueError("Llama-Mesh is not installed on this host.")
    raise ValueError(f"Unsupported provider: {provider}")


def _generate_parametric(prompt: str) -> GenerationResult:
    result = generate_parametric_model(prompt)
    return GenerationResult(
        provider="parametric",
        task_id=result.job_id,
        status="completed",
        glb_url=f"/artifacts/{result.job_id}/{result.glb_path.name}",
        raw={
            "shape": result.shape,
            "dimensions_mm": result.dimensions_mm,
            "notes": result.notes,
        },
    )


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
        "type": "text_to_model",
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


def _file_type_from_content_type(content_type: str) -> str:
    content_type = (content_type or "").lower()
    if "png" in content_type:
        return "png"
    if "webp" in content_type:
        return "webp"
    return "jpeg"


async def _upload_tripo_image(
    content: bytes,
    filename: str,
    content_type: str,
) -> Tuple[str, str]:
    url = f"{settings.tripo_base_url}{settings.tripo_upload_endpoint}"
    headers = {"Authorization": f"Bearer {settings.tripo_api_key}"}
    file_type = _file_type_from_content_type(content_type)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            headers=headers,
            files={
                "file": (
                    filename or f"upload.{file_type}",
                    content,
                    content_type or f"image/{file_type}",
                )
            },
        )
        response.raise_for_status()
        payload = response.json()
    token = (
        payload.get("data", {}).get("image_token")
        or payload.get("image_token")
        or payload.get("data", {}).get("file_token")
        or payload.get("file_token")
    )
    if not token:
        raise RuntimeError(f"Tripo upload missing image_token: {payload}")
    return token, file_type


def _image_data_uri(content: bytes, content_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    mime_type = content_type or "image/jpeg"
    return f"data:{mime_type};base64,{encoded}"


async def _generate_tripo_from_image(
    content: bytes,
    filename: str,
    content_type: str,
) -> GenerationResult:
    if not settings.tripo_api_key:
        raise ValueError("TRIPO_API_KEY is required for Tripo generation")

    token, file_type = await _upload_tripo_image(content, filename, content_type)
    url = f"{settings.tripo_base_url}{settings.tripo_create_endpoint}"
    headers = {"Authorization": f"Bearer {settings.tripo_api_key}"}
    payload = {
        "type": "image_to_model",
        "file": {
            "type": file_type,
            "file_token": token,
        },
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


async def _generate_meshy_from_image(
    content: bytes,
    content_type: str,
) -> GenerationResult:
    if not settings.meshy_api_key:
        raise ValueError("MESHY_API_KEY is required for Meshy generation")

    url = f"{settings.meshy_base_url}{settings.meshy_image_create_endpoint}"
    headers = {"Authorization": f"Bearer {settings.meshy_api_key}"}
    payload = {
        "image_url": _image_data_uri(content, content_type),
        "should_texture": False,
        "should_remesh": True,
        "topology": "triangle",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    task_id = data.get("result") or data.get("id") or data.get("task_id")
    if not task_id:
        raise RuntimeError(f"Meshy response missing task id: {data}")

    status_url = f"{settings.meshy_base_url}{settings.meshy_image_status_endpoint}".format(
        task_id=task_id
    )
    return await _poll_generation(
        provider="meshy",
        task_id=str(task_id),
        status_url=status_url,
        headers=headers,
    )


async def generate_model_from_image(
    content: bytes,
    filename: str,
    content_type: str,
    *,
    provider: Optional[str] = None,
) -> GenerationResult:
    provider = (provider or settings.threed_provider).lower()
    if provider == "tripo":
        return await _generate_tripo_from_image(content, filename, content_type)
    if provider == "meshy":
        return await _generate_meshy_from_image(content, content_type)
    if provider == "llama-mesh":
        raise ValueError("Llama-Mesh is not installed on this host.")
    raise ValueError(f"Unsupported image provider: {provider}")

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

            if status in {"failed", "error", "canceled", "cancelled", "banned", "expired", "unknown"}:
                raise RuntimeError(f"{provider} generation failed: {data}")

            if time.monotonic() - start > timeout_s:
                raise TimeoutError(f"{provider} generation timed out after {timeout_s}s")

            await asyncio.sleep(poll_interval_s)
