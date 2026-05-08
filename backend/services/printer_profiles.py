"""Printer profile registry.

A profile carries two kinds of information:

1. **Slicer config** — bed size, nozzle diameter, layer height, the path to a
   PrusaSlicer/Orca config that produces matching G-code.
2. **Printability capabilities** — what overhang angle this printer can hold
   without supports, how thin a wall it can pull cleanly, whether the slicer
   profile turns on tree supports automatically. The manufacturability check
   reads these to decide whether a given design needs a warning.

Capabilities are honest, not heroic. Numbers are sourced from each vendor's
public guidance and the printer's typical out-of-box behavior with PLA. The
defaults are conservative; users running aggressive cooling mods or custom
profiles will print cleaner than the heuristic predicts, which is the right
direction to err.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from config import settings


DEFAULT_PROFILE_ID = "prusa_mk4_default"

Material = Literal["PLA", "PETG", "ABS", "ASA", "TPU", "PA"]


class PrinterProfile(BaseModel):
    id: str
    label: str
    vendor: str = ""
    model: str = ""
    bed_size_mm: tuple[float, float, float] = Field(
        description="(x, y, z) build volume in millimeters."
    )
    nozzle_mm: float
    layer_height_mm: float
    prusaslicer_config_path: str

    # ---- Manufacturability capabilities --------------------------------
    # Overhang angles follow common slicer wording: 0° = vertical wall,
    # 90° = perfectly flat underside. Larger values mean better cooling and
    # more aggressive unsupported geometry. Numbers below capture what each
    # printer routinely holds in the real world.
    max_unsupported_overhang_deg: float = Field(
        default=45.0,
        description=(
            "Steepest unsupported overhang angle the printer holds without "
            "visible artifacts. Measured from vertical. Anything past this "
            "is flagged for supports or reorientation."
        ),
    )
    clean_overhang_deg: float = Field(
        default=55.0,
        description=(
            "Angle below which prints come out clean enough that the warning "
            "is informational, not a real defect. Used to downgrade the "
            "severity ladder for printers with strong cooling."
        ),
    )
    min_wall_thickness_mm: float = Field(
        default=0.8,
        description="Minimum sane wall thickness. Defaults to 2× a 0.4mm nozzle.",
    )
    max_bridge_length_mm: float = Field(
        default=5.0,
        description="Clean unsupported bridge span without sagging.",
    )
    supports_auto_tree: bool = Field(
        default=True,
        description=(
            "Whether this printer's recommended slicer profile auto-generates "
            "tree supports for tough overhangs. If True, mid-range overhangs "
            "are downgraded to info — slicer will handle it."
        ),
    )
    supports_material: bool = True
    material: Material = "PLA"
    notes: str | None = None


def _profile(
    id: str,
    *,
    label: str,
    vendor: str,
    model: str,
    bed: tuple[float, float, float],
    nozzle: float = 0.4,
    layer: float = 0.2,
    max_overhang: float = 45.0,
    clean_overhang: float = 55.0,
    min_wall: float | None = None,
    bridge: float = 5.0,
    auto_tree: bool = True,
    material: Material = "PLA",
    notes: str | None = None,
) -> PrinterProfile:
    """Compact constructor so the registry below stays readable."""
    return PrinterProfile(
        id=id,
        label=label,
        vendor=vendor,
        model=model,
        bed_size_mm=bed,
        nozzle_mm=nozzle,
        layer_height_mm=layer,
        prusaslicer_config_path=settings.prusaslicer_config,
        max_unsupported_overhang_deg=max_overhang,
        clean_overhang_deg=clean_overhang,
        min_wall_thickness_mm=min_wall if min_wall is not None else max(nozzle * 2.0, 0.8),
        max_bridge_length_mm=bridge,
        supports_auto_tree=auto_tree,
        material=material,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Curated profile set. Stay conservative on the capability numbers; real
# printers in real workshops vary, and surprising the user with a failed
# print is worse than nudging them toward an extra orientation tweak.
# ---------------------------------------------------------------------------

_PROFILES_LIST: list[PrinterProfile] = [
    _profile(
        DEFAULT_PROFILE_ID,
        label="Prusa MK4 (default)",
        vendor="Prusa Research",
        model="MK4",
        bed=(250.0, 210.0, 220.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Strong cooling + Nextruder; comfortable up to ~60° overhangs.",
    ),
    _profile(
        "prusa_mk3s_plus",
        label="Prusa MK3S+",
        vendor="Prusa Research",
        model="MK3S+",
        bed=(250.0, 210.0, 210.0),
        max_overhang=50.0,
        clean_overhang=55.0,
        bridge=7.0,
        auto_tree=True,
        notes="The reliable workhorse. Slightly less aggressive cooling than MK4.",
    ),
    _profile(
        "prusa_mini",
        label="Prusa MINI+",
        vendor="Prusa Research",
        model="MINI+",
        bed=(180.0, 180.0, 180.0),
        max_overhang=50.0,
        clean_overhang=55.0,
        bridge=6.0,
        auto_tree=True,
        notes="Smaller bed; otherwise similar capability to MK3S+.",
    ),
    _profile(
        "prusa_xl",
        label="Prusa XL",
        vendor="Prusa Research",
        model="XL",
        bed=(360.0, 360.0, 360.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Large-format CoreXY; conservative PLA defaults.",
    ),
    _profile(
        "bambu_x1c",
        label="Bambu Lab X1 Carbon",
        vendor="Bambu Lab",
        model="X1 Carbon",
        bed=(256.0, 256.0, 256.0),
        max_overhang=60.0,
        clean_overhang=65.0,
        bridge=10.0,
        auto_tree=True,
        notes="Aggressive cooling + AMS; clears 60-65° overhangs reliably.",
    ),
    _profile(
        "bambu_p1s",
        label="Bambu Lab P1S",
        vendor="Bambu Lab",
        model="P1S",
        bed=(256.0, 256.0, 256.0),
        max_overhang=58.0,
        clean_overhang=63.0,
        bridge=9.0,
        auto_tree=True,
        notes="Enclosed CoreXY; close to X1C for PLA/PETG printability.",
    ),
    _profile(
        "bambu_a1",
        label="Bambu Lab A1",
        vendor="Bambu Lab",
        model="A1",
        bed=(256.0, 256.0, 256.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Fast bedslinger with strong part cooling.",
    ),
    _profile(
        "bambu_a1_mini",
        label="Bambu Lab A1 mini",
        vendor="Bambu Lab",
        model="A1 mini",
        bed=(180.0, 180.0, 180.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Bedslinger but excellent cooling; small bed.",
    ),
    _profile(
        "voron_24_350",
        label="Voron 2.4 (350mm)",
        vendor="Voron Design",
        model="2.4 350",
        bed=(350.0, 350.0, 350.0),
        max_overhang=60.0,
        clean_overhang=65.0,
        bridge=10.0,
        auto_tree=True,
        notes="CoreXY enclosed; capability assumes a tuned build with active cooling.",
    ),
    _profile(
        "ender_3_v2",
        label="Creality Ender 3 V2",
        vendor="Creality",
        model="Ender 3 V2",
        bed=(220.0, 220.0, 250.0),
        max_overhang=45.0,
        clean_overhang=50.0,
        bridge=4.0,
        auto_tree=False,
        notes="Entry-level; weaker cooling than direct-drive printers.",
    ),
    _profile(
        "creality_k1",
        label="Creality K1",
        vendor="Creality",
        model="K1",
        bed=(220.0, 220.0, 250.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Enclosed high-speed CoreXY; use conservative defaults until calibrated.",
    ),
    _profile(
        "creality_k1_max",
        label="Creality K1 Max",
        vendor="Creality",
        model="K1 Max",
        bed=(300.0, 300.0, 300.0),
        max_overhang=55.0,
        clean_overhang=60.0,
        bridge=8.0,
        auto_tree=True,
        notes="Larger K1-family bed; printability assumes stock PLA cooling.",
    ),
    _profile(
        "elegoo_neptune_4",
        label="Elegoo Neptune 4",
        vendor="Elegoo",
        model="Neptune 4",
        bed=(225.0, 225.0, 265.0),
        max_overhang=50.0,
        clean_overhang=55.0,
        bridge=6.0,
        auto_tree=True,
        notes="Klipper bedslinger; use moderate overhang assumptions.",
    ),
    _profile(
        "anycubic_kobra_2",
        label="Anycubic Kobra 2",
        vendor="Anycubic",
        model="Kobra 2",
        bed=(220.0, 220.0, 250.0),
        max_overhang=50.0,
        clean_overhang=55.0,
        bridge=6.0,
        auto_tree=True,
        notes="Fast bedslinger profile; conservative for stock cooling.",
    ),
    _profile(
        "generic_fdm_04mm",
        label="Generic 0.4mm FDM",
        vendor="Generic",
        model="0.4mm FDM",
        bed=(220.0, 220.0, 200.0),
        max_overhang=45.0,
        clean_overhang=50.0,
        bridge=4.0,
        auto_tree=False,
        notes="Conservative fallback when the actual printer is unknown.",
    ),
]


_PROFILES: dict[str, PrinterProfile] = {p.id: p for p in _PROFILES_LIST}


def list_profiles() -> list[PrinterProfile]:
    return list(_PROFILES_LIST)


def get_profile(profile_id: str | None = None) -> PrinterProfile:
    profile = _PROFILES.get(profile_id or DEFAULT_PROFILE_ID)
    if profile is None:
        # Unknown id — fall back to the default rather than crashing the build.
        # The frontend may have stored a profile from a future build of the
        # registry; we don't want a missing key to brick an existing design.
        return _PROFILES[DEFAULT_PROFILE_ID]
    return profile


def profile_config_path(profile: PrinterProfile) -> Path | None:
    path = Path(profile.prusaslicer_config_path)
    return path if path.is_file() else None
