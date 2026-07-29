"""Parametric 120 mm hamster wheel assembly for FDM printing.

Coordinate convention:
- XY is the stand base plane; +Z is up.
- The wheel rotates around the Y axis.
- The wheel center is at (0, 0, axle_height).
"""

from __future__ import annotations

import math

from build123d import Align, Box, BuildPart, Compound, Cylinder, Locations, Mode, add


WHEEL_DIAMETER = 120.0
TRACK_WIDTH = 34.0
TREAD_THICKNESS = 2.4
SPOKE_COUNT = 6
SPOKE_WIDTH = 5.0
SPOKE_DEPTH = 4.0
HUB_DIAMETER = 20.0
AXLE_DIAMETER = 5.0
AXLE_CLEARANCE = 0.4
GROUND_CLEARANCE = 8.0
UPRIGHT_WIDTH = 14.0
STAND_THICKNESS = 6.0
STAND_GAP = 2.0
BASE_LENGTH = 90.0
BASE_WIDTH = 54.0
BASE_THICKNESS = 5.0


def make_wheel():
    wheel_radius = WHEEL_DIAMETER / 2.0
    inner_radius = wheel_radius - TREAD_THICKNESS
    hub_radius = HUB_DIAMETER / 2.0
    axle_height = wheel_radius + GROUND_CLEARANCE
    spoke_length = inner_radius - hub_radius + 1.2
    spoke_mid_radius = hub_radius + spoke_length / 2.0 - 0.6
    spoke_y = -(TRACK_WIDTH / 2.0 - SPOKE_DEPTH / 2.0)

    with BuildPart() as tread:
        with Locations((0, 0, axle_height)):
            Cylinder(
                wheel_radius,
                TRACK_WIDTH,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
            Cylinder(
                inner_radius,
                TRACK_WIDTH + 2.0,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
                mode=Mode.SUBTRACT,
            )

    with BuildPart() as wheel:
        add(tread.part)
        with Locations((0, spoke_y, axle_height)):
            Cylinder(
                hub_radius,
                SPOKE_DEPTH,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
        for index in range(SPOKE_COUNT):
            angle_deg = index * 360.0 / SPOKE_COUNT
            angle_rad = math.radians(angle_deg)
            spoke_x = math.sin(angle_rad) * spoke_mid_radius
            spoke_z = axle_height + math.cos(angle_rad) * spoke_mid_radius
            with Locations((spoke_x, spoke_y, spoke_z)):
                Box(
                    SPOKE_WIDTH,
                    SPOKE_DEPTH,
                    spoke_length,
                    rotation=(0, angle_deg, 0),
                    align=(Align.CENTER, Align.CENTER, Align.CENTER),
                )
        with Locations((0, 0, axle_height)):
            Cylinder(
                AXLE_DIAMETER / 2.0 + AXLE_CLEARANCE / 2.0,
                TRACK_WIDTH + 2.0,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
                mode=Mode.SUBTRACT,
            )
    wheel.part.label = "wheel"
    return wheel.part


def make_stand():
    wheel_radius = WHEEL_DIAMETER / 2.0
    axle_height = wheel_radius + GROUND_CLEARANCE
    hub_radius = HUB_DIAMETER / 2.0
    axle_hole_radius = AXLE_DIAMETER / 2.0 + AXLE_CLEARANCE / 2.0
    stand_y = -(TRACK_WIDTH / 2.0 + STAND_GAP + STAND_THICKNESS / 2.0)
    upright_height = axle_height - BASE_THICKNESS

    with BuildPart() as stand:
        Box(
            BASE_LENGTH,
            BASE_WIDTH,
            BASE_THICKNESS,
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        with Locations((0, stand_y, BASE_THICKNESS)):
            Box(
                UPRIGHT_WIDTH,
                STAND_THICKNESS,
                upright_height,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
            )
        with Locations((0, stand_y, axle_height)):
            Cylinder(
                hub_radius + 2.0,
                STAND_THICKNESS,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
            Cylinder(
                axle_hole_radius,
                STAND_THICKNESS + 2.0,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
                mode=Mode.SUBTRACT,
            )
    stand.part.label = "stand"
    return stand.part


def make_axle():
    axle_height = WHEEL_DIAMETER / 2.0 + GROUND_CLEARANCE
    stand_y = -(TRACK_WIDTH / 2.0 + STAND_GAP + STAND_THICKNESS / 2.0)
    axle_min_y = stand_y - STAND_THICKNESS / 2.0 - 1.0
    axle_max_y = TRACK_WIDTH / 2.0 + 1.0
    axle_length = axle_max_y - axle_min_y
    axle_center_y = (axle_min_y + axle_max_y) / 2.0

    with BuildPart() as axle:
        with Locations((0, axle_center_y, axle_height)):
            Cylinder(
                AXLE_DIAMETER / 2.0,
                axle_length,
                rotation=(90, 0, 0),
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
    axle.part.label = "axle"
    return axle.part


def gen_step():
    wheel = make_wheel()
    stand = make_stand()
    axle = make_axle()
    return Compound(children=[wheel, stand, axle], label="hamster_wheel")

