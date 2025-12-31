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

    prusaslicer_path: str = os.getenv(
        "PRUSASLICER_PATH",
        "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer",
    )
    prusaslicer_config: str = str(
        _resolve_path(os.getenv("PRUSASLICER_CONFIG"), Path("config.ini"))
    )
    output_dir: Path = _resolve_path(
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
