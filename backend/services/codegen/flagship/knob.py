"""Cylindrical knob flagship — knurled grip + threaded insert pocket."""

from __future__ import annotations


SCRIPT = '''\
"""Cylindrical knob with knurled outer grip and a press-fit threaded-insert pocket
on the back. Tests rotational symmetry and small-feature patterning.

Editable parameters: outer_diameter, knob_height, knurl_count, knurl_depth,
insert_diameter, insert_depth, top_chamfer.
"""
from build123d import *
from pulsai import param

outer_diameter = param("outer_diameter", 30.0, type="length_mm", min=12.0, max=80.0)
knob_height = param("knob_height", 14.0, type="length_mm", min=6.0, max=40.0)
knurl_count = int(param("knurl_count", 18, type="count", min=6, max=64,
                         doc="Number of knurl flutes around the perimeter."))
knurl_depth = param("knurl_depth", 1.0, type="length_mm", min=0.2, max=4.0,
                    doc="Depth of each knurl groove.")
insert_diameter = param("insert_diameter", 4.5, type="length_mm", min=0.0, max=12.0,
                        doc="Diameter of the threaded-insert pocket. 0 to disable.")
insert_depth = param("insert_depth", 6.0, type="length_mm", min=2.0, max=30.0)
top_chamfer = param("top_chamfer", 1.0, type="length_mm", min=0.0, max=5.0,
                    doc="Chamfer on the top edge for a softer look.")

# @feature: cylinder
with BuildPart() as part:
    Cylinder(radius=outer_diameter / 2, height=knob_height,
             align=(Align.CENTER, Align.CENTER, Align.MIN))
    # Chamfer the top circular edge — a Cylinder has two circular edges
    # (top + bottom). We pick the one with the largest Z position.
    top_edges = part.edges().group_by(Axis.Z)[-1]
    safe_chamfer = min(top_chamfer, outer_diameter * 0.15, knob_height * 0.4)
    if safe_chamfer > 0.05:
        chamfer(top_edges, length=safe_chamfer)
# @end

# @feature: knurls
knurl_radius = outer_diameter / 2 + knurl_depth * 0.4
with BuildPart() as knurled:
    add(part.part)
    with PolarLocations(radius=knurl_radius, count=knurl_count):
        Cylinder(radius=knurl_depth, height=knob_height + 0.4,
                 mode=Mode.SUBTRACT,
                 align=(Align.CENTER, Align.CENTER, Align.MIN))
part = knurled
# @end

# @feature: insert_pocket
if insert_diameter > 0:
    with BuildPart() as drilled:
        add(part.part)
        with Locations((0, 0, 0)):
            Cylinder(radius=insert_diameter / 2, height=insert_depth + 0.1,
                     mode=Mode.SUBTRACT,
                     align=(Align.CENTER, Align.CENTER, Align.MIN))
    part = drilled
# @end

result = part.part
'''


SPEC = {
    "name": "Cylindrical knob",
    "description": "Knurled grip with a press-fit threaded-insert pocket.",
    "script": SCRIPT,
    "test_param": "knurl_count",
    "test_value": 24,
}
