from __future__ import annotations

from services.codegen.library import Snippet


CABLES = {
    "usb_c": (9.0, 3.8),
    "usb_a": (14.0, 7.0),
    "micro_usb": (7.5, 3.0),
    "barrel_5_5x2_1": (8.0, 8.0),
    "rj45": (16.0, 14.0),
}


CABLE_SNIPPETS = [
    Snippet(
        name=f"{name}_cutout",
        intent=f"{name.replace('_', ' ').upper()} rectangular cable cutout.",
        keywords=tuple(name.split("_")) + (name.replace("_", "-"), "cutout", "port"),
        process=("fdm", "cnc"),
        code=(
            f"cutout_width_mm = {width}\n"
            f"cutout_height_mm = {height}\n"
            "# @feature: cable_cutout\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, cz)):\n"
            "        Box(cutout_width_mm, through_depth, cutout_height_mm)\n"
            "# @end\n"
        ),
    )
    for name, (width, height) in CABLES.items()
]


__all__ = ["CABLE_SNIPPETS", "CABLES"]
