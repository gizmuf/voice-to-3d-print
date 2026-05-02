from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from config import settings


DEFAULT_PROFILE_ID = "prusa_mk4_default"


class PrinterProfile(BaseModel):
    id: str
    label: str
    bed_size_mm: tuple[float, float, float] = Field(
        description="(x, y, z) build volume in millimeters."
    )
    nozzle_mm: float
    layer_height_mm: float
    prusaslicer_config_path: str
    supports_material: bool = True
    notes: str | None = None


def _default_profile() -> PrinterProfile:
    return PrinterProfile(
        id=DEFAULT_PROFILE_ID,
        label="Prusa MK4 (default)",
        bed_size_mm=(250.0, 210.0, 220.0),
        nozzle_mm=0.4,
        layer_height_mm=0.2,
        prusaslicer_config_path=settings.prusaslicer_config,
        notes="Default Phase 1 profile. Mirrors legacy slicer behavior.",
    )


_PROFILES: dict[str, PrinterProfile] = {DEFAULT_PROFILE_ID: _default_profile()}


def list_profiles() -> list[PrinterProfile]:
    return list(_PROFILES.values())


def get_profile(profile_id: str | None = None) -> PrinterProfile:
    profile = _PROFILES.get(profile_id or DEFAULT_PROFILE_ID)
    if profile is None:
        raise KeyError(f"Unknown printer profile: {profile_id}")
    return profile


def profile_config_path(profile: PrinterProfile) -> Path | None:
    path = Path(profile.prusaslicer_config_path)
    return path if path.is_file() else None
