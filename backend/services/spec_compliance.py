"""Deterministic prompt-to-CAD compliance checks.

The language model may decide *how* to build geometry, but explicit dimensions
and counts are contracts.  This module extracts the small, high-confidence
subset we can verify without another model call and compares it with both the
parameter snapshot and (where trustworthy) the built bounding box.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from services.codegen.models import Build, Design, DesignParameter


_NUMBER = r"-?\d+(?:[.,]\d+)?"
_UNIT = r"(?:mm|cm|millimeters?|millimetres?|milimetr\w*|centimeters?|centimetres?|centymetr\w*)?"


@dataclass(frozen=True)
class ExplicitRequirement:
    parameter: str
    expected: float | int | bool
    source: str


def extract_explicit_requirements(
    prompt: str,
    parameters: Iterable[DesignParameter],
) -> list[ExplicitRequirement]:
    """Extract only unambiguous numeric/boolean requirements from ``prompt``."""
    available = {parameter.name: parameter for parameter in parameters}
    text = _normalize(prompt)
    requirements: dict[str, ExplicitRequirement] = {}

    def add(name: str | None, raw: str | float | int | bool, unit: str = "", source: str = "") -> None:
        if not name or name not in available:
            return
        parameter = available[name]
        if isinstance(raw, bool):
            value: float | int | bool = raw
        else:
            numeric = float(str(raw).replace(",", "."))
            if parameter.type == "length_mm" and _is_cm(unit):
                numeric *= 10.0
            value = int(round(numeric)) if parameter.type == "count" else numeric
        requirements[name] = ExplicitRequirement(name, value, source or prompt.strip())

    # Common maker shorthand: 80x60x30 mm / 8 × 6 × 3 cm.
    triplet = re.search(
        rf"\b({_NUMBER})\s*[x×]\s*({_NUMBER})\s*[x×]\s*({_NUMBER})\s*({_UNIT})\b",
        text,
    )
    if triplet and all(name in available for name in ("width", "depth", "height")):
        unit = triplet.group(4)
        add("width", triplet.group(1), unit, triplet.group(0))
        add("depth", triplet.group(2), unit, triplet.group(0))
        add("height", triplet.group(3), unit, triplet.group(0))

    semantic_patterns: list[tuple[tuple[str, ...], str]] = [
        (("wheel_diameter", "outer_diameter", "diameter"), r"(?:średnic\w*|diameter)"),
        (("track_width", "width", "base_width"), r"(?:szerokoś\w*|width)"),
        (("height", "back_height", "plate_height", "knob_height"), r"(?:wysokoś\w*|height)"),
        (("depth", "base_depth", "insert_depth"), r"(?:głębokoś\w*|depth)"),
        (("wall_thickness", "thickness", "plate_thickness"), r"(?:gruboś\w*\s+(?:ściank\w*|ścian\w*)|wall\s+thickness)"),
        (("rung_count",), r"(?:szczebel\w*|rungs?)"),
        (("spoke_count",), r"(?:szprych\w*|spokes?)"),
        (("slot_count_per_leg", "vent_slot_count", "slot_count"), r"(?:slot\w*|szczelin\w*)"),
        (("knurl_count",), r"(?:knurl\w*|radełk\w*)"),
        (("cable_hole_diameter",), r"(?:otw\w*\s+na\s+kabel|cable\s+hole)"),
        (("axle_clearance",), r"(?:luz\w*\s+(?:osi|wałk\w*)|axle\s+clearance)"),
    ]
    for candidates, label_pattern in semantic_patterns:
        name = _select_candidate(candidates, available, text, label_pattern)
        if not name:
            continue
        match = _value_near_label(text, label_pattern)
        if match:
            add(name, match[0], match[1], match[2])

    # Exact parameter names are the strongest contract and cover expert users.
    for name in available:
        label = re.escape(name.replace("_", " "))
        match = _value_near_label(text, label)
        if match:
            add(name, match[0], match[1], match[2])

    if "open_top" in available:
        if re.search(r"\b(?:open\s+top|without\s+(?:a\s+)?lid|otwart\w*\s+od\s+gór\w*|bez\s+pokryw\w*)\b", text):
            add("open_top", True, source="open top")
        elif re.search(r"\b(?:closed\s+top|with\s+(?:a\s+)?lid|zamknięt\w*\s+od\s+gór\w*|z\s+pokryw\w*)\b", text):
            add("open_top", False, source="closed top")

    return list(requirements.values())


def evaluate_spec_compliance(
    design: Design,
    build: Build | None,
    prompt: str | None = None,
) -> dict[str, Any]:
    source_prompt = prompt or str(design.metadata.get("source_prompt") or "")
    requirements = (
        extract_explicit_requirements(source_prompt, design.parameters)
        if prompt is not None
        else _stored_requirements(design) or extract_explicit_requirements(source_prompt, design.parameters)
    )
    if not requirements:
        return {
            "status": "not_applicable",
            "summary": "No explicit dimensions or counts to verify.",
            "checks": [],
            "repair_parameters": [],
        }

    values = {parameter.name: parameter.value for parameter in design.parameters}
    checks: list[dict[str, Any]] = []
    repair_parameters: list[dict[str, Any]] = []
    for requirement in requirements:
        actual = values.get(requirement.parameter)
        tolerance = _parameter_tolerance(requirement.expected)
        passed = _matches(actual, requirement.expected, tolerance)
        checks.append(
            {
                "kind": "parameter",
                "name": requirement.parameter,
                "expected": requirement.expected,
                "actual": actual,
                "tolerance": tolerance,
                "passed": passed,
                "source": requirement.source,
            }
        )
        if not passed:
            repair_parameters.append(
                {"name": requirement.parameter, "new_value": requirement.expected}
            )

    checks.extend(_geometry_checks(design, build, requirements))
    failed = [check for check in checks if not check["passed"]]
    if failed:
        status = "needs_repair" if repair_parameters else "needs_attention"
        summary = f"{len(failed)} of {len(checks)} explicit requirements do not match the model."
    else:
        status = "passed"
        summary = f"Verified {len(checks)} explicit requirements against parameters and geometry."
    return {
        "status": status,
        "summary": summary,
        "checks": checks,
        "repair_parameters": repair_parameters,
    }


def record_spec_targets(design: Design, prompt: str) -> bool:
    """Merge explicit prompt requirements into the design's lasting contract."""
    requirements = extract_explicit_requirements(prompt, design.parameters)
    return record_parameter_targets(
        design,
        {requirement.parameter: requirement.expected for requirement in requirements},
        source=prompt,
    )


def record_parameter_targets(
    design: Design,
    targets: dict[str, float | int | bool],
    *,
    source: str,
) -> bool:
    if not targets:
        return False
    stored = dict(design.metadata.get("spec_targets") or {})
    for name, expected in targets.items():
        stored[name] = {"expected": expected, "source": source.strip()[:500]}
    design.metadata["spec_targets"] = stored
    return True


def _stored_requirements(design: Design) -> list[ExplicitRequirement]:
    stored = design.metadata.get("spec_targets")
    if not isinstance(stored, dict):
        return []
    available = {parameter.name for parameter in design.parameters}
    out: list[ExplicitRequirement] = []
    for name, payload in stored.items():
        if name not in available or not isinstance(payload, dict) or "expected" not in payload:
            continue
        out.append(
            ExplicitRequirement(
                parameter=name,
                expected=payload["expected"],
                source=str(payload.get("source") or "saved design requirement"),
            )
        )
    return out


def _geometry_checks(
    design: Design,
    build: Build | None,
    requirements: list[ExplicitRequirement],
) -> list[dict[str, Any]]:
    if not build or not build.bounding_box_mm:
        return []
    bbox = build.bounding_box_mm
    template_id = str(design.metadata.get("template_id") or "")
    expected = {requirement.parameter: requirement.expected for requirement in requirements}
    checks: list[dict[str, Any]] = []

    if template_id == "simple_box":
        for axis, name in enumerate(("width", "depth", "height")):
            value = expected.get(name)
            if not isinstance(value, (int, float)):
                continue
            tolerance = max(0.8, abs(float(value)) * 0.015)
            checks.append(_geometry_check(f"bbox_{name}", value, bbox[axis], tolerance))

    if template_id == "hamster_wheel" and isinstance(expected.get("wheel_diameter"), (int, float)):
        diameter = float(expected["wheel_diameter"])
        base_length = float(next((p.value for p in design.parameters if p.name == "base_length"), 0) or 0)
        if diameter >= base_length:
            checks.append(
                _geometry_check(
                    "wheel_outer_extent",
                    diameter,
                    bbox[0],
                    max(1.0, diameter * 0.015),
                )
            )
    return checks


def _geometry_check(name: str, expected: float | int, actual: float, tolerance: float) -> dict[str, Any]:
    return {
        "kind": "geometry",
        "name": name,
        "expected": expected,
        "actual": actual,
        "tolerance": tolerance,
        "passed": abs(float(actual) - float(expected)) <= tolerance,
    }


def _select_candidate(
    candidates: tuple[str, ...],
    available: dict[str, DesignParameter],
    text: str,
    label_pattern: str,
) -> str | None:
    present = [candidate for candidate in candidates if candidate in available]
    if not present:
        return None
    if "wheel_diameter" in present and re.search(r"(?:kołowrot\w*|wheel)", text):
        return "wheel_diameter"
    if "track_width" in present and re.search(r"(?:bieżn\w*|track|kołowrot\w*|wheel)", text):
        return "track_width"
    exact = [name for name in present if re.search(rf"\b{re.escape(name.replace('_', ' '))}\b", text)]
    if len(exact) == 1:
        return exact[0]
    return present[0] if len(present) == 1 else None


def _value_near_label(text: str, label_pattern: str) -> tuple[str, str, str] | None:
    after = re.search(rf"(?:{label_pattern})[^\d-]{{0,28}}({_NUMBER})\s*({_UNIT})", text)
    if after:
        return after.group(1), after.group(2), after.group(0)
    before = re.search(rf"({_NUMBER})\s*({_UNIT})[^\w]{{0,8}}(?:{label_pattern})", text)
    if before:
        return before.group(1), before.group(2), before.group(0)
    return None


def _matches(actual: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    try:
        return math.isclose(float(actual), float(expected), abs_tol=tolerance, rel_tol=0.0)
    except (TypeError, ValueError):
        return False


def _parameter_tolerance(expected: Any) -> float:
    if isinstance(expected, bool) or isinstance(expected, int):
        return 0.0
    return max(0.05, abs(float(expected)) * 0.001)


def _is_cm(unit: str) -> bool:
    return bool(re.search(r"^(?:cm|centymetr|centimet)", unit or ""))


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower().replace("−", "-")).strip()


__all__ = [
    "ExplicitRequirement",
    "evaluate_spec_compliance",
    "extract_explicit_requirements",
    "record_parameter_targets",
    "record_spec_targets",
]
