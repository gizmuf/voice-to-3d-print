from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _resolve_path(value: str | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = (Path(__file__).parent / path).resolve()
    return path


def _resolve_output_dir(value: str | None, default: Path) -> Path:
    primary = _resolve_path(value, default)
    try:
        primary.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = default.resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@dataclass(frozen=True)
class Settings:
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    deepgram_base_url: str = os.getenv("DEEPGRAM_BASE_URL", "https://api.deepgram.com")
    deepgram_model: str = os.getenv("DEEPGRAM_MODEL", "nova-2")
    gemini_proxy_url: str = os.getenv(
        "GEMINI_PROXY_URL",
        "https://gut-feeling-api-242245666842.us-central1.run.app/generate",
    )
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    firebase_project_id: str = os.getenv("FIREBASE_PROJECT_ID", "")
    firebase_storage_bucket: str = os.getenv("FIREBASE_STORAGE_BUCKET", "")
    storage_public_base_url: str = os.getenv("STORAGE_PUBLIC_BASE_URL", "")

    threed_provider: str = os.getenv("THREED_PROVIDER", "meshy")
    meshy_api_key: str = os.getenv("MESHY_API_KEY", "")
    tripo_api_key: str = os.getenv("TRIPO_API_KEY", "")
    meshy_base_url: str = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai")
    tripo_base_url: str = os.getenv("TRIPO_BASE_URL", "https://api.tripo3d.ai")
    meshy_create_endpoint: str = os.getenv("MESHY_CREATE_ENDPOINT", "/openapi/v2/text-to-3d")
    meshy_status_endpoint: str = os.getenv("MESHY_STATUS_ENDPOINT", "/openapi/v2/text-to-3d/{task_id}")
    meshy_image_create_endpoint: str = os.getenv(
        "MESHY_IMAGE_CREATE_ENDPOINT",
        "/openapi/v1/image-to-3d",
    )
    meshy_image_status_endpoint: str = os.getenv(
        "MESHY_IMAGE_STATUS_ENDPOINT",
        "/openapi/v1/image-to-3d/{task_id}",
    )
    tripo_create_endpoint: str = os.getenv("TRIPO_CREATE_ENDPOINT", "/v2/openapi/task")
    tripo_status_endpoint: str = os.getenv("TRIPO_STATUS_ENDPOINT", "/v2/openapi/task/{task_id}")
    tripo_upload_endpoint: str = os.getenv("TRIPO_UPLOAD_ENDPOINT", "/v2/openapi/upload/sts")
    trellis2_api_url: str = os.getenv("TRELLIS2_API_URL", "")
    trellis2_image_endpoint: str = os.getenv("TRELLIS2_IMAGE_ENDPOINT", "/image-to-3d")
    trellis2_text_endpoint: str = os.getenv("TRELLIS2_TEXT_ENDPOINT", "")
    trellis2_status_endpoint: str = os.getenv("TRELLIS2_STATUS_ENDPOINT", "")
    trellis2_pipeline_type: str = os.getenv("TRELLIS2_PIPELINE_TYPE", "")
    trellis2_seed: str = os.getenv("TRELLIS2_SEED", "")
    triposr_root: str = os.getenv("TRIPOSR_ROOT", "")
    triposr_python: str = os.getenv("TRIPOSR_PYTHON", "python3")
    triposr_device: str = os.getenv("TRIPOSR_DEVICE", "cpu")
    triposr_model: str = os.getenv("TRIPOSR_MODEL", "stabilityai/TripoSR")
    triposr_cache_dir: str = os.getenv("TRIPOSR_CACHE_DIR", "")
    triposr_timeout_s: int = int(os.getenv("TRIPOSR_TIMEOUT_S", "3600"))
    triposr_chunk_size: str = os.getenv("TRIPOSR_CHUNK_SIZE", "")
    triposr_mc_resolution: str = os.getenv("TRIPOSR_MC_RESOLUTION", "")
    triposr_no_remove_bg: bool = os.getenv("TRIPOSR_NO_REMOVE_BG", "").lower() in (
        "1",
        "true",
        "yes",
    )
    triposr_bake_texture: bool = os.getenv("TRIPOSR_BAKE_TEXTURE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    triposr_texture_resolution: str = os.getenv("TRIPOSR_TEXTURE_RESOLUTION", "")

    prusaslicer_path: str = os.getenv(
        "PRUSASLICER_PATH",
        "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    )
    prusaslicer_config: str = str(
        _resolve_path(os.getenv("PRUSASLICER_CONFIG"), Path("config.ini"))
    )
    output_dir: Path = _resolve_output_dir(
        os.getenv("OUTPUT_DIR"),
        Path(__file__).parent / "data" / "output",
    )
    model_library_path: Path = _resolve_path(
        os.getenv("MODEL_LIBRARY_PATH"),
        Path(__file__).parent / "data" / "model_library.json",
    )
    sketchfab_api_token: str = os.getenv("SKETCHFAB_API_TOKEN", "")
    sketchfab_base_url: str = os.getenv("SKETCHFAB_BASE_URL", "https://api.sketchfab.com/v3")

    mesh_merge_tolerance: float = float(os.getenv("MESH_MERGE_TOLERANCE", "0.0005"))


settings = Settings()
