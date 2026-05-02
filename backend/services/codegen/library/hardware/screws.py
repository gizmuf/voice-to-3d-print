from __future__ import annotations

from services.codegen.library import Snippet


SCREW_SIZES = {
    "M2": {"clearance": 2.4, "tap": 1.6, "head": 4.0},
    "M2.5": {"clearance": 2.9, "tap": 2.05, "head": 5.0},
    "M3": {"clearance": 3.4, "tap": 2.5, "head": 6.0},
    "M4": {"clearance": 4.5, "tap": 3.3, "head": 8.0},
    "M5": {"clearance": 5.5, "tap": 4.2, "head": 10.0},
    "M6": {"clearance": 6.6, "tap": 5.0, "head": 12.0},
}


SCREW_SNIPPETS = [
    Snippet(
        name=f"{size.lower().replace('.', '_')}_screw_clearance",
        intent=f"{size} screw clearance hole with optional counterbore.",
        keywords=(size.lower(), f"{size.lower()} screw", "clearance", "counterbore", "mounting hole"),
        process=("fdm", "cnc"),
        code=(
            f"screw_clearance_diameter = {dims['clearance']}\n"
            f"screw_head_diameter = {dims['head']}\n"
            "# @feature: screw_clearance\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, 0)):\n"
            "        Cylinder(radius=screw_clearance_diameter/2, height=through_depth)\n"
            "    if counterbore_depth > 0:\n"
            "        with Locations((cx, cy, through_depth - counterbore_depth)):\n"
            "            Cylinder(radius=screw_head_diameter/2, height=counterbore_depth, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
            "# @end\n"
        ),
        notes=f"{size}: clearance {dims['clearance']}mm, tap drill {dims['tap']}mm, typical head pocket {dims['head']}mm.",
    )
    for size, dims in SCREW_SIZES.items()
]


__all__ = ["SCREW_SNIPPETS", "SCREW_SIZES"]
