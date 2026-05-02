"""Searchable library of build123d snippets the agent can reference.

The agent calls ``query_library(intent)`` and receives a small list of named
snippets that match. Each snippet is a self-contained block of build123d the
agent can paste into a feature, possibly edited, to produce a particular
geometric pattern.

This is the "show, don't tell" half of the system prompt — the system prompt
teaches the API; the library teaches *idioms*.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Snippet:
    name: str
    intent: str
    keywords: tuple[str, ...]
    process: tuple[str, ...]  # ("fdm",), ("cnc",), or ("fdm","cnc")
    code: str
    notes: str = ""


SNIPPETS: list[Snippet] = [
    Snippet(
        name="circular_hole",
        intent="Add a single round through-hole.",
        keywords=("hole", "round", "circular", "drill"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: hole\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _hole:\n"
            "    with Locations((cx, cy, 0)):\n"
            "        Cylinder(radius=hole_diameter/2, height=through_depth)\n"
            "# @end\n"
        ),
        notes="Subtract from the active BuildPart; set cx, cy, hole_diameter, through_depth before the block.",
    ),
    Snippet(
        name="polygon_hole",
        intent="N-sided polygon hole (triangle, hex, etc.) for venting or aesthetics.",
        keywords=("triangle", "hexagon", "polygon", "vent", "shape"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: polygon_hole\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _ph:\n"
            "    with BuildSketch(Plane.XY) as _sk:\n"
            "        with Locations((cx, cy)):\n"
            "            RegularPolygon(radius=hole_size/2, side_count=sides)\n"
            "    extrude(amount=through_depth)\n"
            "# @end\n"
        ),
        notes="`sides=3` triangle, `sides=6` hexagon, etc.",
    ),
    Snippet(
        name="slot",
        intent="Elongated slot hole.",
        keywords=("slot", "obround", "oblong"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: slot\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _slot:\n"
            "    with BuildSketch(Plane.XY) as _sk:\n"
            "        with Locations((cx, cy)):\n"
            "            SlotOverall(slot_length, slot_width)\n"
            "    extrude(amount=through_depth)\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="circular_pattern_holes",
        intent="Pattern a hole around a center N times.",
        keywords=("pattern", "ring", "circular pattern", "around"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: ring\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _ring:\n"
            "    with PolarLocations(radius=ring_radius, count=count):\n"
            "        Cylinder(radius=hole_diameter/2, height=through_depth)\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="grid_pattern_holes",
        intent="Rectangular grid of holes.",
        keywords=("grid", "array", "matrix", "honeycomb-like"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: grid\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _grid:\n"
            "    with GridLocations(x_spacing, y_spacing, x_count, y_count):\n"
            "        Cylinder(radius=hole_diameter/2, height=through_depth)\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="hex_grid",
        intent="Hexagonal honeycomb grid of holes — ideal speaker grilles, vents.",
        keywords=("honeycomb", "hex grid", "hex pattern"),
        process=("fdm",),
        code=(
            "# @feature: hex_grid\n"
            "with BuildPart(mode=Mode.SUBTRACT) as _hg:\n"
            "    with HexLocations(apothem=cell_apothem, x_count=x_count, y_count=y_count):\n"
            "        with BuildSketch() as _hexsk:\n"
            "            RegularPolygon(radius=hole_size/2, side_count=6)\n"
            "        extrude(amount=through_depth)\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="fillet_top_edges",
        intent="Round the top edges of the active part.",
        keywords=("fillet", "round", "soften", "edges"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: fillet\n"
            "with BuildPart() as _f:\n"
            "    add(part.part)\n"
            "    fillet(_f.edges().group_by(Axis.Z)[-1], radius=fillet_radius)\n"
            "part = _f\n"
            "# @end\n"
        ),
        notes="Replaces `part` with the filleted version.",
    ),
    Snippet(
        name="chamfer_top_edges",
        intent="Chamfer the top edges of the active part.",
        keywords=("chamfer", "bevel"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: chamfer\n"
            "with BuildPart() as _c:\n"
            "    add(part.part)\n"
            "    chamfer(_c.edges().group_by(Axis.Z)[-1], length=chamfer_length)\n"
            "part = _c\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="shell_open_top",
        intent="Hollow out a part, leaving the top face open.",
        keywords=("shell", "hollow", "wall thickness", "open top"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: shell\n"
            "with BuildPart() as _s:\n"
            "    add(part.part)\n"
            "    offset(amount=-wall_thickness, openings=_s.faces().sort_by(Axis.Z)[-1])\n"
            "part = _s\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="counterbore_hole",
        intent="Threaded-bolt counterbore (cylindrical pocket above a through hole).",
        keywords=("counterbore", "cbore", "screw head"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: counterbore\n"
            "with BuildPart(mode=Mode.SUBTRACT):\n"
            "    with Locations((cx, cy, 0)):\n"
            "        Cylinder(radius=through_diameter/2, height=through_depth)\n"
            "    with Locations((cx, cy, through_depth - cbore_depth)):\n"
            "        Cylinder(radius=cbore_diameter/2, height=cbore_depth, align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="boss_with_hole",
        intent="Cylindrical boss (raised cylinder) with a coaxial through-hole.",
        keywords=("boss", "post", "mount", "tower"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: boss\n"
            "with BuildPart() as _boss:\n"
            "    with Locations((cx, cy, 0)):\n"
            "        Cylinder(radius=boss_diameter/2, height=boss_height)\n"
            "    with Locations((cx, cy, 0)):\n"
            "        Cylinder(radius=hole_diameter/2, height=boss_height + 1, mode=Mode.SUBTRACT)\n"
            "# @end\n"
        ),
    ),
    Snippet(
        name="rounded_box",
        intent="Rectangular box with rounded vertical edges.",
        keywords=("box", "rounded", "case"),
        process=("fdm", "cnc"),
        code=(
            "# @feature: shell\n"
            "with BuildPart() as part:\n"
            "    Box(width, depth, height)\n"
            "    fillet(part.edges().filter_by(Axis.Z), radius=corner_radius)\n"
            "# @end\n"
        ),
    ),
]


def search(intent: str, *, process: str | None = None, limit: int = 5) -> list[Snippet]:
    """Tiny lexical scorer: counts keyword hits + name hits."""
    needle = intent.lower()
    candidates = SNIPPETS
    if process:
        candidates = [s for s in candidates if process in s.process]
    scored: list[tuple[int, Snippet]] = []
    for snip in candidates:
        score = 0
        if snip.name in needle:
            score += 5
        for kw in snip.keywords:
            if kw in needle:
                score += 2
        if snip.intent.lower() in needle or needle in snip.intent.lower():
            score += 1
        if score:
            scored.append((score, snip))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [snip for _, snip in scored[:limit]]


def all_snippets() -> list[Snippet]:
    return list(SNIPPETS)


__all__ = ["Snippet", "search", "all_snippets", "SNIPPETS"]
