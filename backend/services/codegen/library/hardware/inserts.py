from __future__ import annotations

from services.codegen.library import Snippet


INSERTS = {
    "M2": (3.2, 3.0),
    "M2.5": (3.8, 4.0),
    "M3": (4.6, 5.7),
    "M4": (6.3, 8.1),
    "M5": (7.1, 9.5),
}


INSERT_SNIPPETS = [
    Snippet(
        name=f"{size.lower().replace('.', '_')}_heat_set_insert",
        intent=f"Heat-set insert pocket for {size}.",
        keywords=(size.lower(), f"{size.lower()} insert", "heat-set", "threaded insert", "voron insert"),
        process=("fdm",),
        code=(
            f"insert_pocket_diameter = {diameter}\n"
            f"insert_pocket_depth = {depth}\n"
            "# @feature: heat_set_insert_pocket\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, pocket_z)):\n"
            "        Cylinder(radius=insert_pocket_diameter/2, height=insert_pocket_depth)\n"
            "# @end\n"
        ),
        notes=f"{size} heat-set insert starter pocket: {diameter}mm diameter x {depth}mm depth.",
    )
    for size, (diameter, depth) in INSERTS.items()
]


__all__ = ["INSERT_SNIPPETS", "INSERTS"]
