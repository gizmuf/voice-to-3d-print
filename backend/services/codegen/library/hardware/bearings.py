from __future__ import annotations

from services.codegen.library import Snippet


BEARINGS = {
    "608": (8, 22, 7),
    "624": (4, 13, 5),
    "625": (5, 16, 5),
    "6800": (10, 19, 5),
    "6801": (12, 21, 5),
    "6802": (15, 24, 5),
}


BEARING_SNIPPETS = [
    Snippet(
        name=f"{name}_bearing_pocket",
        intent=f"{name} bearing pocket.",
        keywords=(name, f"{name} bearing", "bearing pocket", "press fit"),
        process=("fdm", "cnc"),
        code=(
            f"bearing_id_mm = {inner}\n"
            f"bearing_od_mm = {outer}\n"
            f"bearing_width_mm = {width}\n"
            "# @feature: bearing_pocket\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, pocket_z)):\n"
            "        Cylinder(radius=(bearing_od_mm + fit_clearance_mm)/2, height=bearing_width_mm + depth_clearance_mm)\n"
            "# @end\n"
        ),
        notes=f"{name}: ID {inner}mm, OD {outer}mm, width {width}mm.",
    )
    for name, (inner, outer, width) in BEARINGS.items()
]


__all__ = ["BEARING_SNIPPETS", "BEARINGS"]
