"""Flagship workflows.

Five representative designs that double as integration test fixtures. Every
phase from 1 onward must keep all five building cleanly and accepting the
named test mutation. They protect us from generic CAD plumbing drifting
away from real maker use cases.

The five are intentionally diverse:

- ``wall_hook``    — flat plate + hook arm + screw counterbores (fillets, csinks)
- ``phone_stand``  — angled back, base, lip, cable hole (oblique geometry, holes)
- ``knob``         — knurled cylinder with threaded insert pocket (rotational symmetry, knurl)
- ``bracket``      — right-angle plate with elongated slots (multi-plane geometry, slots)
- ``enclosure``    — open-top box with screw bosses + USB cutout + vents (boolean composition)

If any phase breaks any of these, the phase doesn't pass its verification gate.
"""

from __future__ import annotations

from typing import TypedDict


class FlagshipSpec(TypedDict):
    name: str
    description: str
    script: str
    test_param: str
    test_value: float | int | bool | str


from services.codegen.flagship import (  # noqa: E402
    bracket as _bracket,
    enclosure as _enclosure,
    knob as _knob,
    phone_stand as _phone_stand,
    wall_hook as _wall_hook,
)


FLAGSHIPS: dict[str, FlagshipSpec] = {
    "wall_hook": _wall_hook.SPEC,
    "phone_stand": _phone_stand.SPEC,
    "knob": _knob.SPEC,
    "bracket": _bracket.SPEC,
    "enclosure": _enclosure.SPEC,
}


def list_flagships() -> list[dict]:
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in FLAGSHIPS.items()
    ]


def get_flagship(flagship_id: str) -> FlagshipSpec:
    if flagship_id not in FLAGSHIPS:
        raise KeyError(f"Unknown flagship: {flagship_id}")
    return FLAGSHIPS[flagship_id]


__all__ = ["FlagshipSpec", "FLAGSHIPS", "list_flagships", "get_flagship"]
