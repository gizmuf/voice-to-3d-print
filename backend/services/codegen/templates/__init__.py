"""Built-in seed scripts for common starting points.

Each function returns a build123d Python script as a string. The agent and
the API both call ``seed_for(intent)`` to pick a template from a natural
language prompt; from there everything is just script editing.

These are not "templates" in the limited Phase-1 sense — they're starting
points. After seed, the script can be edited, replaced, or grown without
any matrix gating.
"""

from __future__ import annotations

import re

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


HAMSTER_WHEEL = '''\
"""Freestanding hamster wheel with a continuous tread, axle and printable stand."""
from build123d import *
from pulsai import param
import math

wheel_diameter = param("wheel_diameter", 120.0, type="length_mm", min=80.0, max=260.0,
                       doc="Outside diameter of the running wheel.")
track_width = param("track_width", 34.0, type="length_mm", min=24.0, max=70.0,
                    doc="Usable width of the continuous running tread.")
tread_thickness = param("tread_thickness", 2.4, type="length_mm", min=1.6, max=5.0,
                        doc="Radial thickness of the continuous tread.")
spoke_count = int(param("spoke_count", 6, type="count", min=3, max=12,
                        doc="Number of radial support ribs."))
spoke_width = param("spoke_width", 5.0, type="length_mm", min=3.0, max=12.0)
spoke_depth = param("spoke_depth", 4.0, type="length_mm", min=2.4, max=10.0)
hub_diameter = param("hub_diameter", 20.0, type="length_mm", min=12.0, max=36.0)
axle_diameter = param("axle_diameter", 5.0, type="length_mm", min=3.0, max=10.0)
axle_clearance = param("axle_clearance", 0.4, type="length_mm", min=0.2, max=1.2)
ground_clearance = param("ground_clearance", 8.0, type="length_mm", min=4.0, max=24.0)
upright_width = param("upright_width", 14.0, type="length_mm", min=8.0, max=30.0)
stand_thickness = param("stand_thickness", 6.0, type="length_mm", min=4.0, max=14.0)
stand_gap = param("stand_gap", 2.0, type="length_mm", min=1.0, max=8.0)
base_length = param("base_length", 90.0, type="length_mm", min=60.0, max=180.0)
base_width = param("base_width", 54.0, type="length_mm", min=35.0, max=120.0)
base_thickness = param("base_thickness", 5.0, type="length_mm", min=3.0, max=12.0)

wheel_radius = wheel_diameter / 2.0
inner_radius = wheel_radius - tread_thickness
hub_radius = hub_diameter / 2.0
axle_radius = axle_diameter / 2.0
axle_hole_radius = axle_radius + axle_clearance / 2.0
axle_height = wheel_radius + ground_clearance
spoke_length = inner_radius - hub_radius + 1.2
spoke_mid_radius = hub_radius + spoke_length / 2.0 - 0.6
spoke_y = -(track_width / 2.0 - spoke_depth / 2.0)

# @feature: continuous_tread
with BuildPart() as wheel:
    with Locations((0, 0, axle_height)):
        Cylinder(
            radius=wheel_radius,
            height=track_width,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
        Cylinder(
            radius=inner_radius,
            height=track_width + 2.0,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
            mode=Mode.SUBTRACT,
        )
# @end

# @feature: hub_and_spokes
with BuildPart() as wheel_supported:
    add(wheel.part)
    with Locations((0, spoke_y, axle_height)):
        Cylinder(
            radius=hub_radius,
            height=spoke_depth,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    for index in range(spoke_count):
        angle_deg = index * 360.0 / spoke_count
        angle_rad = math.radians(angle_deg)
        spoke_x = math.sin(angle_rad) * spoke_mid_radius
        spoke_z = axle_height + math.cos(angle_rad) * spoke_mid_radius
        with Locations((spoke_x, spoke_y, spoke_z)):
            Box(
                spoke_width,
                spoke_depth,
                spoke_length,
                rotation=(0, angle_deg, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
    with Locations((0, 0, axle_height)):
        Cylinder(
            radius=axle_hole_radius,
            height=track_width + 2.0,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
            mode=Mode.SUBTRACT,
        )
wheel = wheel_supported
# @end

stand_y = -(track_width / 2.0 + stand_gap + stand_thickness / 2.0)
upright_height = axle_height - base_thickness

# @feature: stable_stand
with BuildPart() as stand:
    Box(
        base_length,
        base_width,
        base_thickness,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    with Locations((0, stand_y, base_thickness)):
        Box(
            upright_width,
            stand_thickness,
            upright_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
    with Locations((0, stand_y, axle_height)):
        Cylinder(
            radius=hub_radius + 2.0,
            height=stand_thickness,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
        Cylinder(
            radius=axle_hole_radius,
            height=stand_thickness + 2.0,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
            mode=Mode.SUBTRACT,
        )
# @end

# @feature: axle
axle_min_y = stand_y - stand_thickness / 2.0 - 1.0
axle_max_y = track_width / 2.0 + 1.0
axle_length = axle_max_y - axle_min_y
axle_center_y = (axle_min_y + axle_max_y) / 2.0
with BuildPart() as axle:
    with Locations((0, axle_center_y, axle_height)):
        Cylinder(
            radius=axle_radius,
            height=axle_length,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
# @end

wheel.part.label = "wheel"
stand.part.label = "stand"
axle.part.label = "axle"
result = Compound(children=[wheel.part, stand.part, axle.part], label="hamster_wheel")
'''


JEWELRY_PIECE = '''\
"""Editable flat jewelry starter for sketches, charms, pendants, earrings, brooches, and links."""
from build123d import *
from pulsai import param

width = param("width", 42.0, type="length_mm", min=8.0, max=220.0)
height = param("height", 58.0, type="length_mm", min=8.0, max=260.0)
thickness = param("thickness", 2.2, type="length_mm", min=0.8, max=8.0)
edge_bevel = param("edge_bevel", 0.6, type="length_mm", min=0.0, max=3.0)
connector_outer = param("connector_outer", 8.0, type="length_mm", min=3.0, max=24.0)
connector_inner = param("connector_inner", 3.2, type="length_mm", min=1.0, max=16.0)
relief_depth = param("relief_depth", 0.35, type="length_mm", min=0.0, max=2.0)

# @feature: body
with BuildPart() as part:
    Box(width, height, thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    with Locations((0, height * 0.18, 0)):
        Cylinder(radius=width * 0.28, height=thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    with Locations((0, -height * 0.2, 0)):
        Cylinder(radius=width * 0.22, height=thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if edge_bevel > 0:
        fillet(part.edges().filter_by(Axis.Z), radius=edge_bevel)
# @end

# @feature: connector
with BuildPart() as connected:
    add(part.part)
    with Locations((0, height / 2 + connector_outer * 0.42, 0)):
        Cylinder(radius=connector_outer / 2, height=thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        Cylinder(radius=connector_inner / 2, height=thickness * 1.4,
                 mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
part = connected
# @end

# @feature: openwork
with BuildPart() as pierced:
    add(part.part)
    for x, y, r in [
        (-width * 0.22, height * 0.12, width * 0.08),
        (width * 0.2, height * 0.03, width * 0.07),
        (-width * 0.05, -height * 0.18, width * 0.09),
    ]:
        with Locations((x, y, 0)):
            Cylinder(radius=r, height=thickness * 1.5,
                     mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
part = pierced
# @end

# @feature: raised_detail
if relief_depth > 0:
    with BuildPart() as detailed:
        add(part.part)
        z = thickness / 2 + relief_depth / 2
        with Locations((0, 0, z)):
            Box(width * 0.08, height * 0.72, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((-width * 0.18, height * 0.1, z)):
            Box(width * 0.28, width * 0.05, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((width * 0.16, -height * 0.1, z)):
            Box(width * 0.24, width * 0.05, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = detailed
# @end

result = part.part
'''


JEWELRY_CROSS = '''\
"""Editable cross pendant starter with chain loop, openwork, and raised branch detail."""
from build123d import *
from pulsai import param

width = param("width", 34.0, type="length_mm", min=12.0, max=140.0)
height = param("height", 58.0, type="length_mm", min=18.0, max=180.0)
thickness = param("thickness", 2.0, type="length_mm", min=0.8, max=8.0)
arm_width = param("arm_width", 10.0, type="length_mm", min=3.0, max=40.0)
edge_bevel = param("edge_bevel", 0.45, type="length_mm", min=0.0, max=2.5)
connector_outer = param("connector_outer", 7.5, type="length_mm", min=3.0, max=24.0)
connector_inner = param("connector_inner", 3.0, type="length_mm", min=1.0, max=16.0)
relief_depth = param("relief_depth", 0.35, type="length_mm", min=0.0, max=2.0)

# @feature: cross_body
with BuildPart() as part:
    Box(arm_width, height, thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    with Locations((0, height * 0.18, 0)):
        Box(width, arm_width, thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    if edge_bevel > 0:
        fillet(part.edges().filter_by(Axis.Z), radius=edge_bevel)
# @end

# @feature: bail
with BuildPart() as bailed:
    add(part.part)
    with Locations((0, height / 2 + connector_outer * 0.35, 0)):
        Cylinder(radius=connector_outer / 2, height=thickness, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        Cylinder(radius=connector_inner / 2, height=thickness * 1.4,
                 mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
part = bailed
# @end

# @feature: pierced_openwork
with BuildPart() as pierced:
    add(part.part)
    for x, y, r in [
        (-width * 0.24, height * 0.18, 2.0),
        (width * 0.24, height * 0.18, 2.0),
        (-arm_width * 0.18, height * 0.02, 2.1),
        (arm_width * 0.2, -height * 0.18, 2.3),
        (-arm_width * 0.18, -height * 0.34, 1.8),
    ]:
        with Locations((x, y, 0)):
            Cylinder(radius=r, height=thickness * 1.5,
                     mode=Mode.SUBTRACT, align=(Align.CENTER, Align.CENTER, Align.CENTER))
part = pierced
# @end

# @feature: raised_branch
if relief_depth > 0:
    with BuildPart() as detailed:
        add(part.part)
        z = thickness / 2 + relief_depth / 2
        with Locations((0, -height * 0.04, z)):
            Box(arm_width * 0.22, height * 0.82, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((-width * 0.18, height * 0.14, z)):
            Box(width * 0.36, arm_width * 0.16, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
        with Locations((width * 0.14, -height * 0.12, z)):
            Box(width * 0.24, arm_width * 0.14, relief_depth, align=(Align.CENTER, Align.CENTER, Align.CENTER))
    part = detailed
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


_HAMSTER_RUNG_FEATURE = '''# @feature: continuous_tread
rung_count = int(param("rung_count", 24, type="count", min=8, max=48,
                       doc="Number of transverse rungs across the running track."))
rung_diameter = param("rung_diameter", 4.0, type="length_mm", min=2.0, max=8.0,
                      doc="Diameter of each transverse rung.")
ring_mid_radius = wheel_radius - tread_thickness / 2.0
flange_y_left = -(track_width / 2.0 - tread_thickness / 2.0)
flange_y_right = track_width / 2.0 - tread_thickness / 2.0
wheel_tread_parts = []

# Keep the rings and rungs as a compound of valid solids. Fusing dozens of
# touching cylinders is unnecessary for printing and dominates preview time.
with BuildPart() as left_ring:
    with Locations((0, flange_y_left, axle_height)):
        Torus(
            major_radius=ring_mid_radius,
            minor_radius=tread_thickness / 2.0,
            rotation=(90, 0, 0),
        )
wheel_tread_parts.append(left_ring.part)

with BuildPart() as right_ring:
    with Locations((0, flange_y_right, axle_height)):
        Torus(
            major_radius=ring_mid_radius,
            minor_radius=tread_thickness / 2.0,
            rotation=(90, 0, 0),
        )
wheel_tread_parts.append(right_ring.part)

# Transverse rungs across the track; these are not radial spokes.
for index in range(rung_count):
    angle_rad = math.radians(360.0 * index / rung_count)
    rung_x = ring_mid_radius * math.cos(angle_rad)
    rung_z = axle_height + ring_mid_radius * math.sin(angle_rad)
    with BuildPart() as rung:
        with Locations((rung_x, 0, rung_z)):
            Cylinder(
                radius=rung_diameter / 2.0,
                height=track_width,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
    wheel_tread_parts.append(rung.part)
wheel_tread = Compound(children=wheel_tread_parts, label="continuous_tread")
# @end

# @feature: hub_and_spokes
with BuildPart() as wheel_support:
    with Locations((0, spoke_y, axle_height)):
        Cylinder(
            radius=hub_radius,
            height=spoke_depth,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
        )
    for index in range(spoke_count):
        angle_deg = index * 360.0 / spoke_count
        angle_rad = math.radians(angle_deg)
        spoke_x = math.sin(angle_rad) * spoke_mid_radius
        spoke_z = axle_height + math.cos(angle_rad) * spoke_mid_radius
        with Locations((spoke_x, spoke_y, spoke_z)):
            Box(
                spoke_width,
                spoke_depth,
                spoke_length,
                rotation=(0, angle_deg, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
    with Locations((0, 0, axle_height)):
        Cylinder(
            radius=axle_hole_radius,
            height=track_width + 2.0,
            rotation=(90, 0, 0),
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
            mode=Mode.SUBTRACT,
        )
wheel_shape = Compound(children=[wheel_tread, wheel_support.part], label="wheel")
# @end'''


def _measurement_mm(prompt: str, labels: str) -> float | None:
    match = re.search(
        rf"(?:{labels})\w*\s*(?:=|:)?\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|centymetr\w*)",
        prompt,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    return value * 10.0 if unit == "cm" or unit.startswith("centymetr") else value


def _rung_count(prompt: str) -> int | None:
    match = re.search(
        r"(\d+)\s*(?:szczebel\w*|rung\w*)",
        prompt,
        flags=re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _replace_param_default(script: str, name: str, value: float | int) -> str:
    rendered = str(int(value)) if isinstance(value, int) else f"{value:.1f}"
    return re.sub(
        rf'(param\("{re.escape(name)}",\s*)[-+]?\d+(?:\.\d+)?',
        rf"\g<1>{rendered}",
        script,
        count=1,
    )


def _hamster_wheel_seed(prompt: str) -> str:
    script = HAMSTER_WHEEL
    rung_count = _rung_count(prompt)
    if rung_count is not None and 8 <= rung_count <= 48:
        script = re.sub(
            r"# @feature: continuous_tread\n.*?# @end\n\n# @feature: hub_and_spokes\n.*?# @end",
            _HAMSTER_RUNG_FEATURE,
            script,
            count=1,
            flags=re.DOTALL,
        )
        script = script.replace('wheel.part.label = "wheel"', 'wheel_shape.label = "wheel"')
        script = script.replace(
            "Compound(children=[wheel.part, stand.part, axle.part]",
            "Compound(children=[wheel_shape, stand.part, axle.part]",
        )
        script = _replace_param_default(script, "rung_count", rung_count)

    diameter = _measurement_mm(prompt, r"średnic|srednic|diameter")
    width = _measurement_mm(prompt, r"szerokoś|szerokos|width")
    if diameter is not None and 80.0 <= diameter <= 260.0:
        script = _replace_param_default(script, "wheel_diameter", diameter)
    if width is not None and 24.0 <= width <= 70.0:
        script = _replace_param_default(script, "track_width", width)
    return script


def prompt_seed_is_complete(prompt: str, template_id: str | None) -> bool:
    """Whether the deterministic seed fully satisfies the explicit prompt.

    This deliberately stays conservative: unsupported mounting/bearing requests
    still go to the CAD agent, while the common hamster-wheel dimensions and
    rung count are handled locally and immediately.
    """
    if template_id != "hamster_wheel":
        return False
    needle = (prompt or "").lower()
    unsupported = (
        "przyssawk",
        "suction",
        "łożysk",
        "lozysk",
        "bearing",
        "wall mount",
        "ścienn",
        "scienn",
    )
    if any(word in needle for word in unsupported):
        return False
    if ("szczebel" in needle or "rung" in needle) and _rung_count(prompt) is None:
        return False
    if any(word in needle for word in ("średnic", "srednic", "diameter")):
        diameter = _measurement_mm(prompt, r"średnic|srednic|diameter")
        if diameter is None or not 80.0 <= diameter <= 260.0:
            return False
    if any(word in needle for word in ("szerokoś", "szerokos", "width")):
        width = _measurement_mm(prompt, r"szerokoś|szerokos|width")
        if width is None or not 24.0 <= width <= 70.0:
            return False
    return True


_SEED_SCRIPTS: dict[str, tuple[str, str]] = {
    # template_id -> (display name, build123d script)
    "perforated_disc": ("Perforated disc", PERFORATED_DISC),
    "phone_stand": ("Phone stand", PHONE_STAND),
    "simple_box": ("Simple box", SIMPLE_BOX),
    "cylindrical_holder": ("Cylindrical holder", CYLINDRICAL_HOLDER),
    "hamster_wheel": ("Hamster wheel", HAMSTER_WHEEL),
    "jewelry_piece": ("Jewelry sketch starter", JEWELRY_PIECE),
    "jewelry_cross": ("Cross pendant starter", JEWELRY_CROSS),
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
    "hamster_wheel": (
        "hamster wheel", "running wheel", "exercise wheel", "kołowrotek",
        "kolowrotek", "chomik", "chomika", "terrarium",
    ),
    "jewelry_piece": (
        "jewelry", "jewellery", "pendant", "necklace", "bracelet", "earring",
        "brooch", "charm", "wearable", "castable resin", "resin jewelry",
    ),
    "jewelry_cross": ("cross", "crucifix"),
}


def list_template_ids() -> list[str]:
    return list(_SEED_SCRIPTS.keys())


def get_seed_script(template_id: str) -> tuple[str, str]:
    if template_id not in _SEED_SCRIPTS:
        raise KeyError(f"Unknown template_id: {template_id}")
    return _SEED_SCRIPTS[template_id]


def _keyword_hit(text: str, keyword: str) -> bool:
    if len(keyword) <= 3 and keyword.isalpha():
        return bool(re.search(rf"\b{re.escape(keyword)}\b", text))
    return keyword in text


def match_template_id(prompt: str) -> str | None:
    """Return a genuinely matched template id, never a cosmetic fallback."""
    needle = (prompt or "").lower()
    if any(_keyword_hit(needle, kw) for kw in _KEYWORDS["jewelry_cross"]):
        return "jewelry_cross"
    if any(_keyword_hit(needle, kw) for kw in _KEYWORDS["jewelry_piece"]):
        return "jewelry_piece"
    best: tuple[str, int] | None = None
    for tid, kws in _KEYWORDS.items():
        score = sum(1 for kw in kws if _keyword_hit(needle, kw))
        if best is None or score > best[1]:
            best = (tid, score)
    return best[0] if best is not None and best[1] > 0 else None


def seed_for(prompt: str) -> tuple[str, str, str]:
    """Pick a template from a free-form prompt; return (template_id, name, script)."""
    tid = match_template_id(prompt) or "simple_box"
    name, script = _SEED_SCRIPTS[tid]
    if tid == "hamster_wheel":
        script = _hamster_wheel_seed(prompt)
    return tid, name, script


__all__ = [
    "list_template_ids",
    "get_seed_script",
    "match_template_id",
    "prompt_seed_is_complete",
    "seed_for",
]
