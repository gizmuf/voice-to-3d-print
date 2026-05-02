"""Wall hook flagship — flat back plate + curved hook arm + screw counterbores."""

from __future__ import annotations


SCRIPT = '''\
"""Wall hook — flat back plate, curved hook arm, two countersunk screw holes.

Editable parameters: plate_width, plate_height, plate_thickness, hook_reach,
hook_thickness, hook_drop, screw_hole_diameter, screw_hole_spacing.
"""
from build123d import *
from pulsai import param

plate_width = param("plate_width", 36.0, type="length_mm", min=20.0, max=120.0,
                    doc="Width of the back plate (mm).")
plate_height = param("plate_height", 60.0, type="length_mm", min=30.0, max=200.0,
                     doc="Height of the back plate (mm).")
plate_thickness = param("plate_thickness", 4.0, type="length_mm", min=2.0, max=15.0,
                        doc="Plate thickness — back-to-front depth.")
hook_reach = param("hook_reach", 28.0, type="length_mm", min=10.0, max=120.0,
                   doc="How far the hook extends out from the wall.")
hook_thickness = param("hook_thickness", 6.0, type="length_mm", min=3.0, max=20.0,
                       doc="Cross-section thickness of the hook arm.")
hook_drop = param("hook_drop", 18.0, type="length_mm", min=5.0, max=80.0,
                  doc="How far the hook tip drops below the arm root.")
screw_hole_diameter = param("screw_hole_diameter", 4.0, type="length_mm",
                            min=2.0, max=10.0,
                            doc="Through-hole diameter for the mounting screws.")
screw_hole_spacing = param("screw_hole_spacing", 30.0, type="length_mm",
                           min=10.0, max=180.0,
                           doc="Vertical spacing between the two screw holes.")

# @feature: plate
with BuildPart() as part:
    Box(plate_thickness, plate_width, plate_height,
        align=(Align.MIN, Align.CENTER, Align.MIN))
    # Round only the four vertical (Z-axis) edges of the front face — keeps
    # build robust across OCCT versions; full edge fillets exceed the
    # available material on thin plates.
    fillet_r = min(plate_thickness * 0.4, 2.0)
    if fillet_r > 0.1:
        fillet(part.edges().filter_by(Axis.Z), radius=fillet_r)
# @end

# @feature: hook_arm
hook_z = plate_height * 0.7
arm_y_extent = max(hook_reach * 0.6, hook_thickness * 1.5)
with BuildPart() as arm:
    add(part.part)
    with Locations((plate_thickness, 0, hook_z)):
        Box(hook_reach, hook_thickness, hook_thickness,
            align=(Align.MIN, Align.CENTER, Align.MIN))
    # Drop the tip
    with Locations((plate_thickness + hook_reach - hook_thickness, 0, hook_z - hook_drop)):
        Box(hook_thickness, hook_thickness, hook_drop + hook_thickness,
            align=(Align.MIN, Align.CENTER, Align.MIN))
part = arm
# @end

# @feature: screw_holes
csink_diameter = screw_hole_diameter * 2.0
csink_depth = plate_thickness * 0.4
hole_centers = [
    (0, 0, plate_height / 2 + screw_hole_spacing / 2),
    (0, 0, plate_height / 2 - screw_hole_spacing / 2),
]
with BuildPart() as drilled:
    add(part.part)
    for cx, cy, cz in hole_centers:
        with Locations((cx, cy, cz)):
            Cylinder(radius=screw_hole_diameter / 2, height=plate_thickness * 1.4,
                     mode=Mode.SUBTRACT,
                     align=(Align.MIN, Align.CENTER, Align.CENTER),
                     rotation=(0, 90, 0))
        with Locations((cx, cy, cz)):
            Cylinder(radius=csink_diameter / 2, height=csink_depth + 0.1,
                     mode=Mode.SUBTRACT,
                     align=(Align.MIN, Align.CENTER, Align.CENTER),
                     rotation=(0, 90, 0))
part = drilled
# @end

result = part.part
'''


SPEC = {
    "name": "Wall hook",
    "description": "Flat back plate with curved hook arm and two countersunk mounting holes.",
    "script": SCRIPT,
    "test_param": "screw_hole_diameter",
    "test_value": 5.5,
}
