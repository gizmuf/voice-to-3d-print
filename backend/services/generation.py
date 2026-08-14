from __future__ import annotations

import asyncio
import base64
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
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
    if provider == "trellis2":
        return await _generate_trellis2(prompt)
    if provider == "triposr":
        raise ValueError("TripoSR is image-to-3D only. Use /generate-image.")
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
    if not settings.allow_platform_ai_spend:
        raise ValueError("Platform-paid Meshy generation is disabled; use a customer-owned provider key.")
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
    if not settings.allow_platform_ai_spend:
        raise ValueError("Platform-paid Tripo generation is disabled; use a customer-owned provider key.")
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


def _trellis2_payload(prompt: str | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if prompt:
        payload["prompt"] = prompt
    if settings.trellis2_pipeline_type:
        payload["pipeline_type"] = settings.trellis2_pipeline_type
    if settings.trellis2_seed:
        try:
            payload["seed"] = int(settings.trellis2_seed)
        except ValueError:
            payload["seed"] = settings.trellis2_seed
    return payload


async def _generate_trellis2(prompt: str) -> GenerationResult:
    if not settings.trellis2_api_url or not settings.trellis2_text_endpoint:
        raise ValueError(
            "TRELLIS2_API_URL and TRELLIS2_TEXT_ENDPOINT are required for Trellis2 text generation."
        )

    url = f"{settings.trellis2_api_url}{settings.trellis2_text_endpoint}"
    payload = _trellis2_payload(prompt)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    glb_url = _extract_glb_url(data)
    task_id = data.get("task_id") or data.get("id") or data.get("result") or "trellis2"
    if glb_url:
        return GenerationResult(
            provider="trellis2",
            task_id=str(task_id),
            status="completed",
            glb_url=glb_url,
            raw=data,
        )

    if settings.trellis2_status_endpoint and task_id:
        status_url = f"{settings.trellis2_api_url}{settings.trellis2_status_endpoint}".format(
            task_id=task_id
        )
        return await _poll_generation(
            provider="trellis2",
            task_id=str(task_id),
            status_url=status_url,
            headers={},
        )

    raise RuntimeError(f"Trellis2 response missing glb_url: {data}")


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
    if not settings.allow_platform_ai_spend:
        raise ValueError("Platform-paid Tripo generation is disabled; use a customer-owned provider key.")
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
    if not settings.allow_platform_ai_spend:
        raise ValueError("Platform-paid Meshy generation is disabled; use a customer-owned provider key.")
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


async def _generate_trellis2_from_image(
    content: bytes,
    filename: str,
    content_type: str,
) -> GenerationResult:
    if not settings.trellis2_api_url:
        raise ValueError("TRELLIS2_API_URL is required for Trellis2 generation")

    url = f"{settings.trellis2_api_url}{settings.trellis2_image_endpoint}"
    payload = _trellis2_payload()
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            url,
            data=payload,
            files={
                "image": (
                    filename or "upload.png",
                    content,
                    content_type or "image/png",
                )
            },
        )
        response.raise_for_status()
        data = response.json()

    glb_url = _extract_glb_url(data)
    task_id = data.get("task_id") or data.get("id") or data.get("result") or "trellis2"
    if glb_url:
        return GenerationResult(
            provider="trellis2",
            task_id=str(task_id),
            status="completed",
            glb_url=glb_url,
            raw=data,
        )

    if settings.trellis2_status_endpoint and task_id:
        status_url = f"{settings.trellis2_api_url}{settings.trellis2_status_endpoint}".format(
            task_id=task_id
        )
        return await _poll_generation(
            provider="trellis2",
            task_id=str(task_id),
            status_url=status_url,
            headers={},
        )

    raise RuntimeError(f"Trellis2 response missing glb_url: {data}")


def _triposr_env() -> Dict[str, str]:
    env = os.environ.copy()
    if settings.triposr_cache_dir:
        env["HF_HOME"] = settings.triposr_cache_dir
        env["TRANSFORMERS_CACHE"] = settings.triposr_cache_dir
        env["TORCH_HOME"] = settings.triposr_cache_dir
        env["XDG_CACHE_HOME"] = settings.triposr_cache_dir
    return env


def _triposr_output_paths(job_id: str, filename: str) -> tuple[Path, Path]:
    output_root = Path(settings.output_dir) / job_id / "triposr"
    output_root.mkdir(parents=True, exist_ok=True)
    ext = Path(filename).suffix or ".png"
    input_path = output_root / f"input{ext}"
    return output_root, input_path


def _triposr_glb_path(output_root: Path) -> Path:
    default_path = output_root / "0" / "mesh.glb"
    if default_path.exists():
        return default_path
    candidates = list(output_root.rglob("*.glb"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError("TripoSR output GLB not found.")


async def _generate_triposr_from_image(
    content: bytes,
    filename: str,
    content_type: str,
    *,
    job_id: Optional[str] = None,
) -> GenerationResult:
    if not settings.triposr_root:
        raise ValueError("TRIPOSR_ROOT is required for local TripoSR generation.")

    root = Path(settings.triposr_root).expanduser()
    run_path = root / "run.py"
    if not run_path.exists():
        raise ValueError(f"TripoSR run.py not found at {run_path}")

    job_id = job_id or uuid.uuid4().hex
    output_root, input_path = _triposr_output_paths(job_id, filename)
    input_path.write_bytes(content)

    cmd = [
        settings.triposr_python,
        "run.py",
        str(input_path),
        "--output-dir",
        str(output_root),
        "--model-save-format",
        "glb",
        "--device",
        settings.triposr_device,
        "--pretrained-model-name-or-path",
        settings.triposr_model,
    ]
    if settings.triposr_chunk_size:
        cmd.extend(["--chunk-size", settings.triposr_chunk_size])
    if settings.triposr_mc_resolution:
        cmd.extend(["--mc-resolution", settings.triposr_mc_resolution])
    if settings.triposr_no_remove_bg:
        cmd.append("--no-remove-bg")
    if settings.triposr_bake_texture:
        cmd.append("--bake-texture")
    if settings.triposr_texture_resolution:
        cmd.extend(["--texture-resolution", settings.triposr_texture_resolution])

    await asyncio.to_thread(
        subprocess.run,
        cmd,
        cwd=root,
        env=_triposr_env(),
        check=True,
        timeout=settings.triposr_timeout_s,
    )

    glb_path = _triposr_glb_path(output_root)
    output_dir = Path(settings.output_dir)
    rel_path = glb_path.relative_to(output_dir)
    glb_url = f"/artifacts/{rel_path.as_posix()}"
    return GenerationResult(
        provider="triposr",
        task_id=job_id,
        status="completed",
        glb_url=glb_url,
        raw={
            "output_path": str(glb_path),
            "content_type": content_type,
        },
    )


async def generate_model_from_image(
    content: bytes,
    filename: str,
    content_type: str,
    *,
    job_id: Optional[str] = None,
    provider: Optional[str] = None,
) -> GenerationResult:
    provider = (provider or settings.threed_provider).lower()
    if provider == "tripo":
        return await _generate_tripo_from_image(content, filename, content_type)
    if provider == "meshy":
        return await _generate_meshy_from_image(content, content_type)
    if provider == "trellis2":
        return await _generate_trellis2_from_image(content, filename, content_type)
    if provider == "triposr":
        return await _generate_triposr_from_image(
            content,
            filename,
            content_type,
            job_id=job_id,
        )
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
