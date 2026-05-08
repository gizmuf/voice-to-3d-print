from __future__ import annotations

from pathlib import Path

import pytest
import trimesh

from services.codegen.ast_audit import audit_script
from services.codegen.engine import audit_then_run


BAD_CUTTER_LEAK_SCRIPT = """
from build123d import *

with BuildPart() as part:
    Box(20, 20, 4)
    cutter = Pos(0, 0, 0) * Cylinder(radius=2, height=8)
    add(cutter, mode=Mode.SUBTRACT)

result = part.part
"""


SAFE_CUP_RING_SCRIPT = """
from build123d import *
from pulsai import param
import math

height = param("height", 90.0, type="length_mm", min=60.0, max=150.0)
outer_diameter = param("outer_diameter", 80.0, type="length_mm", min=50.0, max=150.0)
wall_thickness = param("wall_thickness", 3.0, type="length_mm", min=1.5, max=10.0)
bottom_thickness = param("bottom_thickness", 3.0, type="length_mm", min=1.5, max=10.0)
hole_diameter = param("hole_diameter", 5.6, type="length_mm", min=1.0, max=20.0)
hole_count = int(param("hole_count", 10, type="count", min=1, max=24))
hole_zone_fraction = param("hole_zone_fraction", 0.75, type="ratio", min=0.1, max=0.95)

# @feature: body
with BuildPart() as cup:
    Cylinder(
        radius=outer_diameter / 2,
        height=height,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    inner_radius = outer_diameter / 2 - wall_thickness
    inner_height = height - bottom_thickness
    with Locations((0, 0, bottom_thickness)):
        Cylinder(
            radius=inner_radius,
            height=inner_height,
            mode=Mode.SUBTRACT,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
# @end

# @feature: side_holes
hole_z = height * hole_zone_fraction
angle_step = 360.0 / hole_count
outer_radius = outer_diameter / 2
inner_radius = outer_radius - wall_thickness
hole_center_radius = (outer_radius + inner_radius) / 2
cut_length = wall_thickness + 2.0 * hole_diameter

hole_cutters = []
for idx in range(hole_count):
    angle_deg = idx * angle_step
    angle_rad = math.radians(angle_deg)
    x = math.cos(angle_rad) * hole_center_radius
    y = math.sin(angle_rad) * hole_center_radius
    cutter = (
        Pos(x, y, hole_z)
        * Rot(0, 0, angle_deg)
        * Cylinder(
            radius=hole_diameter / 2,
            height=cut_length,
            rotation=(0, 90, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    )
    hole_cutters.append(cutter)

with BuildPart() as holed:
    add(cup.part)
    for cutter in hole_cutters:
        add(cutter, mode=Mode.SUBTRACT)
# @end

result = holed.part
"""


def _load_mesh(path: str | Path) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))
    return mesh


def test_audit_rejects_assigned_primitive_inside_buildpart() -> None:
    result = audit_script(BAD_CUTTER_LEAK_SCRIPT)

    assert not result.ok
    assert any("auto-adds geometry" in error for error in result.errors)


def test_cup_side_hole_ring_stays_single_body_at_75_percent_height(tmp_path: Path) -> None:
    result = audit_then_run(
        script=SAFE_CUP_RING_SCRIPT,
        targets=["stl"],
        workspace_dir=tmp_path,
    )

    assert result.ok, result.payload
    assert result.payload["bbox_mm"] == pytest.approx((80.0, 80.0, 90.0), abs=0.15)

    mesh = _load_mesh(result.payload["artifacts"]["stl"])
    components = mesh.split(only_watertight=False)
    assert len(components) == 1

    vertices = mesh.vertices
    z_min = float(vertices[:, 2].min())
    z_max = float(vertices[:, 2].max())
    assert z_min == pytest.approx(0.0, abs=0.05)
    assert z_max == pytest.approx(90.0, abs=0.05)

    # Vertices on the cylindrical hole walls should cluster near 75% height,
    # not at the rim. This catches the centered-cylinder coordinate drift that
    # placed "height / 2" holes around z=45 on a -45..+45 body.
    expected_z = 90.0 * 0.75
    ring_band = vertices[
        (vertices[:, 2] > expected_z - 3.5)
        & (vertices[:, 2] < expected_z + 3.5)
    ]
    assert len(ring_band) > 50
