from __future__ import annotations

from services.codegen.library import Snippet


MAGNETS = [(6, 3), (8, 3), (10, 3), (12, 3)]


MAGNET_SNIPPETS = [
    Snippet(
        name=f"disc_magnet_{diameter}x{height}",
        intent=f"{diameter}x{height}mm disc magnet pocket.",
        keywords=(f"{diameter}x{height}", "disc magnet", "magnet pocket"),
        process=("fdm", "cnc"),
        code=(
            f"magnet_diameter_mm = {diameter}\n"
            f"magnet_depth_mm = {height}\n"
            "# @feature: magnet_pocket\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, pocket_z)):\n"
            "        Cylinder(radius=(magnet_diameter_mm + fit_clearance_mm)/2, height=magnet_depth_mm)\n"
            "# @end\n"
        ),
    )
    for diameter, height in MAGNETS
]


__all__ = ["MAGNET_SNIPPETS", "MAGNETS"]
