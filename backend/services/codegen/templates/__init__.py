"""Built-in seed scripts for common starting points.

Each function returns a build123d Python script as a string. The agent and
the API both call ``seed_for(intent)`` to pick a template from a natural
language prompt; from there everything is just script editing.

These are not "templates" in the limited Phase-1 sense — they're starting
points. After seed, the script can be edited, replaced, or grown without
any matrix gating.
"""

from __future__ import annotations

PERFORATED_DISC = '''\
"""Perforated disc — speaker grilles, vents, plant-pot drainage discs.

Editable parameters: outer_diameter, thickness, hole_diameter, ring_count,
center_hole_diameter, edge_margin.
"""
from build123d import *
from pulsai import param

outer_diameter = param("outer_diameter", 340.0, type="length_mm", min=40, max=600,
                       doc="Outer diameter of the disc.")
thickness = param("thickness", 5.0, type="length_mm", min=1.0, max=30.0,
                  doc="Disc thickness along Z.")
hole_diameter = param("hole_diameter", 7.0, type="length_mm", min=0.5, max=40.0,
                      doc="Diameter of each pattern hole.")
ring_count = int(param("ring_count", 12, type="count", min=1, max=40,
                       doc="Number of concentric rings of holes."))
edge_margin = param("edge_margin", 8.0, type="length_mm", min=2.0, max=60.0,
                    doc="Solid margin between outermost ring and disc edge.")
center_hole_diameter = param("center_hole_diameter", 16.0, type="length_mm",
                             min=0.0, max=120.0, doc="Center hole diameter (set 0 to disable).")

# @feature: body
with BuildPart() as part:
    Cylinder(radius=outer_diameter/2, height=thickness)
# @end

# @feature: pattern
ring_spacing = max((outer_diameter/2 - edge_margin - center_hole_diameter/2 - hole_diameter)
                   / max(ring_count - 1, 1), hole_diameter * 1.2)
inner_radius = center_hole_diameter/2 + hole_diameter
with BuildPart() as patterned:
    add(part.part)
    for i in range(ring_count):
        ring_radius = inner_radius + i * ring_spacing
        circumference = 2 * 3.14159265 * ring_radius
        per_ring = max(int(circumference / max(hole_diameter * 1.4, 0.1)), 6)
        with PolarLocations(radius=ring_radius, count=per_ring):
            Cylinder(radius=hole_diameter/2, height=thickness * 1.2,
                     mode=Mode.SUBTRACT)
part = patterned
# @end

# @feature: center_hole
if center_hole_diameter > 0:
    with BuildPart() as drilled:
        add(part.part)
        Cylinder(radius=center_hole_diameter/2, height=thickness * 1.2,
                 mode=Mode.SUBTRACT)
    part = drilled
# @end

result = part.part
'''


PHONE_STAND = '''\
"""Adjustable-angle phone stand."""
from build123d import *
from pulsai import param

width = param("width", 80.0, type="length_mm", min=50.0, max=200.0)
depth = param("depth", 90.0, type="length_mm", min=50.0, max=200.0)
height = param("height", 120.0, type="length_mm", min=50.0, max=300.0)
base_thickness = param("base_thickness", 6.0, type="length_mm", min=2.0, max=30.0)
back_thickness = param("back_thickness", 5.0, type="length_mm", min=2.0, max=30.0)
angle_deg = param("angle_deg", 65.0, type="angle_deg", min=30.0, max=85.0)
lip_height = param("lip_height", 12.0, type="length_mm", min=2.0, max=40.0)
cable_hole_diameter = param("cable_hole_diameter", 10.0, type="length_mm", min=0.0, max=40.0)

import math
angle_rad = math.radians(angle_deg)

# @feature: base
with BuildPart() as part:
    Box(width, depth, base_thickness, align=(Align.CENTER, Align.CENTER, Align.MIN))
# @end

# @feature: back
with BuildPart() as back:
    add(part.part)
    with BuildSketch(Plane.XZ) as sk:
        with Locations((0, base_thickness)):
            Rectangle(width, height, align=(Align.CENTER, Align.MIN))
    extrude(amount=back_thickness, mode=Mode.ADD)
    # rotate the back to the requested angle
part = back
# @end

# @feature: lip
with BuildPart() as lipped:
    add(part.part)
    with BuildSketch(Plane.XY.offset(base_thickness)) as lip_sk:
        Rectangle(width, lip_height, align=(Align.CENTER, Align.MIN))
    extrude(amount=lip_height)
part = lipped
# @end

# @feature: cable_hole
if cable_hole_diameter > 0:
    with BuildPart() as drilled:
        add(part.part)
        with Locations((0, depth/4, -1)):
            Cylinder(radius=cable_hole_diameter/2, height=base_thickness + 2,
                     mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = drilled
# @end

result = part.part
'''


SIMPLE_BOX = '''\
"""Rectangular box with rounded vertical corners and an optional open top.

The hollow is implemented as a boolean subtraction (a smaller inner box) rather
than build123d's shell/offset operation, which is much more reliable across
OCCT versions for the kind of parts hobbyists print.
"""
from build123d import *
from pulsai import param

width = param("width", 120.0, type="length_mm", min=20.0, max=400.0)
depth = param("depth", 80.0, type="length_mm", min=20.0, max=400.0)
height = param("height", 40.0, type="length_mm", min=10.0, max=300.0)
wall_thickness = param("wall_thickness", 3.0, type="length_mm", min=1.0, max=20.0)
fillet_radius = param("fillet_radius", 3.0, type="length_mm", min=0.0, max=30.0)
open_top = param("open_top", True, type="boolean")

# @feature: outer
with BuildPart() as part:
    Box(width, depth, height, align=(Align.CENTER, Align.CENTER, Align.MIN))
    if fillet_radius > 0:
        fillet(part.edges().filter_by(Axis.Z), radius=fillet_radius)
# @end

# @feature: hollow
inner_w = max(width - 2 * wall_thickness, 0.5)
inner_d = max(depth - 2 * wall_thickness, 0.5)
if open_top:
    inner_h = max(height - wall_thickness, 0.5) + 1.0  # +1 so the cut clears the top
    z_offset = wall_thickness
else:
    inner_h = max(height - 2 * wall_thickness, 0.5)
    z_offset = wall_thickness
with BuildPart() as cavity:
    add(part.part)
    with Locations((0, 0, z_offset)):
        Box(inner_w, inner_d, inner_h, mode=Mode.SUBTRACT,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
part = cavity
# @end

result = part.part
'''


CYLINDRICAL_HOLDER = '''\
"""Pen / cup / pot-shaped cylindrical holder."""
from build123d import *
from pulsai import param

diameter = param("diameter", 70.0, type="length_mm", min=20.0, max=300.0)
height = param("height", 100.0, type="length_mm", min=20.0, max=400.0)
wall_thickness = param("wall_thickness", 3.0, type="length_mm", min=1.0, max=15.0)
base_thickness = param("base_thickness", 4.0, type="length_mm", min=1.0, max=30.0)

# @feature: outer
with BuildPart() as part:
    Cylinder(radius=diameter/2, height=height,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
# @end

# @feature: hollow
with BuildPart() as hollowed:
    add(part.part)
    Cylinder(radius=diameter/2 - wall_thickness, height=height - base_thickness + 1,
             align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT,
             rotation=(0, 0, 0))
    # shift the subtracted core up by base_thickness
part = hollowed
# @end

result = part.part
'''


IMPORTED_STL = '''\
"""Imported STL — augment with mesh + build123d operations.

The uploaded mesh is pre-loaded as ``imported_mesh`` (a trimesh.Trimesh).
You can:
- Translate, rotate, scale the whole mesh.
- Boolean-add or subtract any build123d Part / trimesh.Trimesh from it.
- Use trimesh utilities (split, smooth, decimate, fix_normals, etc.).
- Run the result through manufacturability checks like any other design.

Assign your final geometry to ``result``. It can be a trimesh.Trimesh
(exported directly) or a build123d Part/Compound (exported via OCCT).
"""
import trimesh
import numpy as np
from pulsai import param

scale_factor = param("scale", 1.0, type="ratio", min=0.05, max=20.0,
                     doc="Uniform scale factor applied to the imported mesh.")
tx = param("translate_x_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0,
           doc="Translate the mesh along X (mm).")
ty = param("translate_y_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0)
tz = param("translate_z_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0)
rotate_z_deg = param("rotate_z_deg", 0.0, type="angle_deg", min=-360.0, max=360.0,
                     doc="Rotate around the Z axis (degrees).")
flatten_to_z0 = param("flatten_to_z0", True, type="boolean",
                      doc="Translate the mesh so its lowest point sits on z=0 (good for FDM).")

# @feature: transform
mesh = imported_mesh.copy()
if scale_factor != 1.0:
    mesh.apply_scale(scale_factor)
if rotate_z_deg != 0.0:
    angle_rad = np.deg2rad(rotate_z_deg)
    R = trimesh.transformations.rotation_matrix(angle_rad, [0, 0, 1])
    mesh.apply_transform(R)
if tx or ty or tz:
    mesh.apply_translation([tx, ty, tz])
if flatten_to_z0:
    mesh.apply_translation([0, 0, -float(mesh.bounds[0][2])])
# @end

# Add boolean operations below by appending features. Examples:
#   replace_feature("transform", ...) to change the transform
#   append_feature("hole", code) to subtract a Cylinder from the mesh
#   rewrite_design(...) for a fundamentally different approach.

result = mesh
'''


IMPORTED_STEP = '''\
"""Imported STEP — operate on the B-rep part with build123d.

Unlike STL, STEP files carry topology. The runner pre-loads the imported
file as ``imported_part`` (a build123d ``Compound``). You can:

- Translate / rotate / scale the whole part.
- Boolean-add or subtract any build123d Part / Solid from it.
- Fillet or chamfer outer edges (where OCCT can resolve the operation).

What you can\'t do (Phase 2 honest scope):

- Edit the part\'s original parametric features. Recognising those is hard
  and unreliable; we treat the imported topology as opaque except for
  augmentation operations.

Assign your final geometry to ``result``. Built-in transform parameters
expose the most useful global edits.
"""
import math
from build123d import *
from pulsai import param

scale_factor = param("scale", 1.0, type="ratio", min=0.05, max=20.0,
                     doc="Uniform scale applied to the imported part.")
tx = param("translate_x_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0)
ty = param("translate_y_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0)
tz = param("translate_z_mm", 0.0, type="length_mm", min=-1000.0, max=1000.0)
rotate_z_deg = param("rotate_z_deg", 0.0, type="angle_deg", min=-360.0, max=360.0)
flatten_to_z0 = param("flatten_to_z0", True, type="boolean",
                      doc="Translate so the lowest point sits on z=0.")

# @feature: transform
shape = imported_part
if scale_factor != 1.0:
    shape = scale(shape, by=scale_factor)
if rotate_z_deg != 0.0:
    shape = Rot(0, 0, rotate_z_deg) * shape
if tx or ty or tz:
    shape = Pos(tx, ty, tz) * shape
if flatten_to_z0:
    bbox = shape.bounding_box()
    shape = Pos(0, 0, -bbox.min.Z) * shape
# @end

result = shape
'''


_SEED_SCRIPTS: dict[str, tuple[str, str]] = {
    # template_id -> (display name, build123d script)
    "perforated_disc": ("Perforated disc", PERFORATED_DISC),
    "phone_stand": ("Phone stand", PHONE_STAND),
    "simple_box": ("Simple box", SIMPLE_BOX),
    "cylindrical_holder": ("Cylindrical holder", CYLINDRICAL_HOLDER),
    "imported_stl": ("Imported STL", IMPORTED_STL),
    "imported_step": ("Imported STEP", IMPORTED_STEP),
}


_KEYWORDS: dict[str, tuple[str, ...]] = {
    "perforated_disc": (
        "perforated", "disc", "grill", "grille", "speaker", "vent", "filter",
        "strainer", "circle", "round", "plate", "flat plate", "discoid", "disk",
        "holes",  # "circle with holes" → perforated_disc
    ),
    "phone_stand": ("phone", "stand", "dock", "tablet", "device"),
    "simple_box": ("box", "container", "case", "enclosure", "tray"),
    "cylindrical_holder": ("holder", "cup", "pen", "vase", "pot", "cylinder"),
}


def list_template_ids() -> list[str]:
    return list(_SEED_SCRIPTS.keys())


def get_seed_script(template_id: str) -> tuple[str, str]:
    if template_id not in _SEED_SCRIPTS:
        raise KeyError(f"Unknown template_id: {template_id}")
    return _SEED_SCRIPTS[template_id]


def seed_for(prompt: str) -> tuple[str, str, str]:
    """Pick a template from a free-form prompt; return (template_id, name, script)."""
    needle = (prompt or "").lower()
    best: tuple[str, int] | None = None
    for tid, kws in _KEYWORDS.items():
        score = sum(1 for kw in kws if kw in needle)
        if best is None or score > best[1]:
            best = (tid, score)
    if best is None or best[1] == 0:
        # default — start with a versatile rounded box
        tid = "simple_box"
    else:
        tid = best[0]
    name, script = _SEED_SCRIPTS[tid]
    return tid, name, script


__all__ = ["list_template_ids", "get_seed_script", "seed_for"]
