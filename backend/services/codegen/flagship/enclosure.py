"""Electronics enclosure — open-top box with screw bosses, USB cutout, vents."""

from __future__ import annotations


SCRIPT = '''\
"""Open-top electronics enclosure with corner screw bosses, a USB cutout on
one wall, and optional ventilation slots on top. Tests boolean composition
across many features.

Editable parameters: width, depth, height, wall_thickness, fillet_radius,
boss_diameter, boss_hole_diameter, usb_cutout_width, usb_cutout_height,
vent_slot_count.
"""
from build123d import *
from pulsai import param

width = param("width", 80.0, type="length_mm", min=30.0, max=300.0)
depth = param("depth", 60.0, type="length_mm", min=30.0, max=300.0)
height = param("height", 30.0, type="length_mm", min=15.0, max=200.0)
wall_thickness = param("wall_thickness", 2.4, type="length_mm", min=1.2, max=8.0)
fillet_radius = param("fillet_radius", 3.0, type="length_mm", min=0.0, max=15.0,
                      doc="Outer-corner fillet for ergonomics.")
boss_diameter = param("boss_diameter", 6.0, type="length_mm", min=3.0, max=15.0,
                      doc="OD of the corner screw bosses.")
boss_hole_diameter = param("boss_hole_diameter", 2.5, type="length_mm",
                           min=0.0, max=8.0,
                           doc="Self-tap pilot hole through each boss.")
usb_cutout_width = param("usb_cutout_width", 12.0, type="length_mm",
                         min=0.0, max=40.0,
                         doc="USB / connector cutout width on the +Y wall. 0 to disable.")
usb_cutout_height = param("usb_cutout_height", 6.0, type="length_mm",
                          min=0.0, max=20.0)
vent_slot_count = int(param("vent_slot_count", 4, type="count", min=0, max=20,
                              doc="Ventilation slots in the top opening. 0 to disable."))

# @feature: shell
with BuildPart() as part:
    Box(width, depth, height,
        align=(Align.CENTER, Align.CENTER, Align.MIN))
    if fillet_radius > 0:
        fillet(part.edges().filter_by(Axis.Z), radius=fillet_radius)

inner_w = max(width - 2 * wall_thickness, 0.5)
inner_d = max(depth - 2 * wall_thickness, 0.5)
inner_h = max(height - wall_thickness, 0.5) + 1.0
with BuildPart() as cavity:
    add(part.part)
    with Locations((0, 0, wall_thickness)):
        Box(inner_w, inner_d, inner_h, mode=Mode.SUBTRACT,
            align=(Align.CENTER, Align.CENTER, Align.MIN))
part = cavity
# @end

# @feature: bosses
boss_inset = wall_thickness * 1.4 + boss_diameter / 2
boss_height = height - wall_thickness - 1.0
corner_offsets = [
    ( width / 2 - boss_inset,  depth / 2 - boss_inset),
    (-width / 2 + boss_inset,  depth / 2 - boss_inset),
    ( width / 2 - boss_inset, -depth / 2 + boss_inset),
    (-width / 2 + boss_inset, -depth / 2 + boss_inset),
]
with BuildPart() as bossed:
    add(part.part)
    for cx, cy in corner_offsets:
        with Locations((cx, cy, wall_thickness)):
            Cylinder(radius=boss_diameter / 2, height=boss_height,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    if boss_hole_diameter > 0:
        for cx, cy in corner_offsets:
            with Locations((cx, cy, wall_thickness - 0.1)):
                Cylinder(radius=boss_hole_diameter / 2,
                         height=boss_height + 0.4,
                         mode=Mode.SUBTRACT,
                         align=(Align.CENTER, Align.CENTER, Align.MIN))
part = bossed
# @end

# @feature: usb_cutout
if usb_cutout_width > 0 and usb_cutout_height > 0:
    cutout_z = wall_thickness + (height - wall_thickness) / 2
    with BuildPart() as cut:
        add(part.part)
        with BuildSketch(Plane.XZ.offset(depth / 2 + 1.0)) as _sk:
            with Locations((0, cutout_z)):
                Rectangle(usb_cutout_width, usb_cutout_height)
        extrude(amount=-(wall_thickness + 2.0), mode=Mode.SUBTRACT)
    part = cut
# @end

result = part.part
'''


SPEC = {
    "name": "Electronics enclosure",
    "description": "Open-top box with corner bosses, USB cutout, optional vents.",
    "script": SCRIPT,
    "test_param": "width",
    "test_value": 100.0,
}
