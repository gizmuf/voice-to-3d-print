"""Manufacturing-intent snippet presets."""

from __future__ import annotations

from services.codegen.library.hardware.bearings import BEARING_SNIPPETS
from services.codegen.library.hardware.cables import CABLE_SNIPPETS
from services.codegen.library.hardware.inserts import INSERT_SNIPPETS
from services.codegen.library.hardware.magnets import MAGNET_SNIPPETS
from services.codegen.library.hardware.screws import SCREW_SNIPPETS


HARDWARE_SNIPPETS = [
    *SCREW_SNIPPETS,
    *BEARING_SNIPPETS,
    *INSERT_SNIPPETS,
    *MAGNET_SNIPPETS,
    *CABLE_SNIPPETS,
]


__all__ = ["HARDWARE_SNIPPETS"]
