"""Phone stand flagship — angled back, base, lip, optional cable hole."""

from __future__ import annotations


SCRIPT = '''\
"""Phone stand — flat base, lip to keep the phone from sliding off, angled back support.

Editable parameters: base_width, base_depth, back_height, base_thickness,
back_thickness, lip_height, support_angle_deg, cable_hole_diameter.
"""
import math
from build123d import *
from pulsai import param

base_width = param("base_width", 80.0, type="length_mm", min=50.0, max=200.0,
                   doc="Width of the base (mm).")
base_depth = param("base_depth", 90.0, type="length_mm", min=50.0, max=200.0,
                   doc="Depth of the base (front-to-back).")
back_height = param("back_height", 110.0, type="length_mm", min=50.0, max=300.0,
                    doc="Height of the angled back support.")
base_thickness = param("base_thickness", 6.0, type="length_mm", min=2.0, max=20.0)
back_thickness = param("back_thickness", 5.0, type="length_mm", min=2.0, max=20.0)
lip_height = param("lip_height", 12.0, type="length_mm", min=3.0, max=40.0,
                   doc="How tall the front lip is.")
support_angle_deg = param("support_angle_deg", 70.0, type="angle_deg",
                          min=45.0, max=85.0,
                          doc="Lean angle of the back support (90° is vertical).")
cable_hole_diameter = param("cable_hole_diameter", 12.0, type="length_mm",
                            min=0.0, max=30.0,
                            doc="Cable pass-through hole at the back. 0 to disable.")

angle_rad = math.radians(support_angle_deg)
back_offset = base_depth * 0.55  # how far back the support sits relative to base center

# @feature: base
with BuildPart() as part:
    Box(base_width, base_depth, base_thickness,
        align=(Align.CENTER, Align.CENTER, Align.MIN))
# @end

# @feature: lip
with BuildPart() as lipped:
    add(part.part)
    with Locations((0, -base_depth / 2, base_thickness)):
        Box(base_width, lip_height, lip_height,
            align=(Align.CENTER, Align.MIN, Align.MIN))
part = lipped
# @end

# @feature: back_support
back_y = -back_offset / 2 + base_depth / 2 - back_thickness / 2
with BuildPart() as backed:
    add(part.part)
    with Locations((0, back_y, base_thickness)):
        Box(base_width, back_thickness, back_height,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
            rotation=(90 - support_angle_deg, 0, 0))
part = backed
# @end

# @feature: cable_hole
if cable_hole_diameter > 0:
    with BuildPart() as drilled:
        add(part.part)
        with Locations((0, base_depth * 0.05, -1)):
            Cylinder(radius=cable_hole_diameter / 2,
                     height=base_thickness + 2,
                     mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = drilled
# @end

result = part.part
'''


SPEC = {
    "name": "Phone stand",
    "description": "Angled back with base + lip; cable hole optional.",
    "script": SCRIPT,
    "test_param": "support_angle_deg",
    "test_value": 65.0,
}
