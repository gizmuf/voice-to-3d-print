"""Right-angle mounting bracket with elongated slots — CNC-friendly."""

from __future__ import annotations


SCRIPT = '''\
"""Right-angle mounting bracket — vertical face + horizontal face, each with
elongated mounting slots. Suitable for shelves, brackets, robot frames, etc.
Cuts cleanly via 3-axis CNC because both slots open to a free face.

Editable parameters: leg_length, width, thickness, fillet_radius,
slot_count_per_leg, slot_length, slot_width.
"""
from build123d import *
from pulsai import param

leg_length = param("leg_length", 60.0, type="length_mm", min=20.0, max=200.0,
                   doc="Length of each leg of the L-bracket.")
width = param("width", 40.0, type="length_mm", min=20.0, max=200.0,
              doc="Width of the bracket (along the corner).")
thickness = param("thickness", 4.0, type="length_mm", min=2.0, max=20.0,
                  doc="Stock thickness.")
fillet_radius = param("fillet_radius", 6.0, type="length_mm", min=0.0, max=20.0,
                      doc="Inside-corner fillet to relieve stress.")
slot_count_per_leg = int(param("slot_count_per_leg", 2, type="count", min=1, max=6,
                                doc="Slots per leg."))
slot_length = param("slot_length", 16.0, type="length_mm", min=4.0, max=60.0)
slot_width = param("slot_width", 5.0, type="length_mm", min=2.0, max=20.0)

# @feature: corner
with BuildPart() as part:
    Box(thickness, width, leg_length,
        align=(Align.MIN, Align.CENTER, Align.MIN))
    Box(leg_length, width, thickness,
        align=(Align.MIN, Align.CENTER, Align.MIN))
    # Inner-corner fillet only — pick the two Y-axis edges at the corner
    # (x ≈ thickness, z ≈ thickness). Filleting all Y-axis edges fights
    # OCCT on the outer edges of an L-shape; keep it conservative.
    safe_fillet = min(fillet_radius, leg_length * 0.4, thickness * 1.2)
    if safe_fillet > 0.1:
        try:
            inner_edges = (
                part.edges()
                .filter_by(Axis.Y)
                .filter_by_position(Axis.X, minimum=thickness * 0.5,
                                    maximum=thickness * 1.5)
                .filter_by_position(Axis.Z, minimum=thickness * 0.5,
                                    maximum=thickness * 1.5)
            )
            if len(inner_edges) > 0:
                fillet(inner_edges, radius=safe_fillet)
        except Exception:
            pass  # leave the corner sharp if OCCT can't fillet here
# @end

# @feature: vertical_slots
slot_step_v = (leg_length - thickness) / (slot_count_per_leg + 1)
with BuildPart() as slotted:
    add(part.part)
    for i in range(slot_count_per_leg):
        z = thickness + slot_step_v * (i + 1)
        with BuildSketch(Plane.YZ.offset(thickness * 1.1)) as _sk:
            with Locations((0, z)):
                SlotOverall(width=slot_length, height=slot_width)
        extrude(amount=-thickness * 1.4, mode=Mode.SUBTRACT)
part = slotted
# @end

# @feature: horizontal_slots
slot_step_h = (leg_length - thickness) / (slot_count_per_leg + 1)
with BuildPart() as slotted_h:
    add(part.part)
    for i in range(slot_count_per_leg):
        x = thickness + slot_step_h * (i + 1)
        with BuildSketch(Plane.XY.offset(thickness * 1.1)) as _sk:
            with Locations((x, 0)):
                SlotOverall(width=slot_length, height=slot_width)
        extrude(amount=-thickness * 1.4, mode=Mode.SUBTRACT)
part = slotted_h
# @end

result = part.part
'''


SPEC = {
    "name": "Right-angle bracket",
    "description": "L-bracket with elongated slots on both faces. CNC-friendly geometry.",
    "script": SCRIPT,
    "test_param": "leg_length",
    "test_value": 80.0,
}
