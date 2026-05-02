"""Parse PrusaSlicer G-code headers to surface print weight, time, and cost.

PrusaSlicer writes comments at the top and end of the G-code file:

    ; estimated printing time (normal mode) = 1h 15m 42s
    ; filament used [g] = 14.32
    ; filament used [cm3] = 11.45

We extract these into a :class:`PrintEstimate`. The cost is computed from a
configurable filament price (``FILAMENT_PRICE_USD_PER_G`` env var, defaults to
$0.025/g — about €18/kg PLA at 2026 prices).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from services.codegen.models import PrintEstimate


_DEFAULT_PRICE_USD_PER_G = 0.025


_TIME_RE = re.compile(
    r"estimated printing time.*?=\s*"
    r"(?:(\d+)\s*d\s*)?(?:(\d+)\s*h\s*)?(?:(\d+)\s*m\s*)?(?:(\d+)\s*s)?",
    re.IGNORECASE,
)
_GRAMS_RE = re.compile(r"filament used\s*\[g\]\s*=\s*([\d.]+)", re.IGNORECASE)
_CM3_RE = re.compile(r"filament used\s*\[cm3\]\s*=\s*([\d.]+)", re.IGNORECASE)


def filament_price_usd_per_g() -> float:
    raw = os.getenv("FILAMENT_PRICE_USD_PER_G")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_PRICE_USD_PER_G


def parse_gcode_estimate(gcode_path: Path) -> PrintEstimate | None:
    """Parse a PrusaSlicer G-code file and return a PrintEstimate.

    Reads up to 2 KB from the head and 4 KB from the tail — the comments we
    care about live in the file's ``configuration block`` near the end and
    in the slicer banner near the start.
    """
    if not gcode_path.exists():
        return None
    try:
        size = gcode_path.stat().st_size
        with gcode_path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(2048)
            if size > 6144:
                fh.seek(max(size - 4096, 0))
                tail = fh.read(4096)
            else:
                tail = ""
        text = head + "\n" + tail
    except OSError:
        return None

    minutes: float | None = None
    m = _TIME_RE.search(text)
    if m:
        d, h, mn, s = (int(g) if g else 0 for g in m.groups())
        total_min = d * 24 * 60 + h * 60 + mn + s / 60
        if total_min > 0:
            minutes = total_min

    grams = None
    g = _GRAMS_RE.search(text)
    if g:
        try:
            grams = float(g.group(1))
        except ValueError:
            pass

    cm3 = None
    c = _CM3_RE.search(text)
    if c:
        try:
            cm3 = float(c.group(1))
        except ValueError:
            pass

    if grams is None and minutes is None:
        return None

    price = filament_price_usd_per_g()
    cost = grams * price if grams is not None else None
    return PrintEstimate(
        filament_g=grams,
        filament_cm3=cm3,
        print_minutes=minutes,
        cost_usd=cost,
        cost_usd_per_g=price,
    )


__all__ = ["parse_gcode_estimate", "filament_price_usd_per_g"]
