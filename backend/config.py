from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    tripo_base_url: str = os.getenv("TRIPO_BASE_URL", "https://api.tripo.ai")
    meshy_create_endpoint: str = os.getenv("MESHY_CREATE_ENDPOINT", "/v1/text-to-3d")
    meshy_status_endpoint: str = os.getenv("MESHY_STATUS_ENDPOINT", "/v1/text-to-3d/{task_id}")
    tripo_create_endpoint: str = os.getenv("TRIPO_CREATE_ENDPOINT", "/v1/task")
    tripo_status_endpoint: str = os.getenv("TRIPO_STATUS_ENDPOINT", "/v1/task/{task_id}")

    prusaslicer_path: str = os.getenv("PRUSASLICER_PATH", "/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer")
    prusaslicer_config: str = os.getenv("PRUSASLICER_CONFIG", "config.ini")
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(Path(__file__).parent / "data" / "output"))).resolve()
    model_library_path: Path = Path(
        os.getenv("MODEL_LIBRARY_PATH", str(Path(__file__).parent / "data" / "model_library.json"))
    ).resolve()
    sketchfab_api_token: str = os.getenv("SKETCHFAB_API_TOKEN", "")
    sketchfab_base_url: str = os.getenv("SKETCHFAB_BASE_URL", "https://api.sketchfab.com/v3")

    mesh_merge_tolerance: float = float(os.getenv("MESH_MERGE_TOLERANCE", "0.0005"))


settings = Settings()
