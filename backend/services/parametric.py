from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import trimesh

from config import settings


@dataclass
class ParametricResult:
    job_id: str
    glb_path: Path
    shape: str
    dimensions_mm: Tuple[float, float, float]
    notes: List[str]


def _extract_numbers(prompt: str) -> List[Tuple[float, str]]:
    matches = re.findall(r"(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?", prompt.lower())
    results: List[Tuple[float, str]] = []
    for value, unit in matches:
        results.append((float(value), unit or "mm"))
    return results


def _to_mm(value: float, unit: str) -> float:
    if unit == "cm":
        return value * 10.0
    if unit in {"in", "inch", "inches"}:
        return value * 25.4
    return value


def _parse_triplet(prompt: str, keyword: Optional[str] = None) -> Optional[Tuple[float, float, float]]:
    pattern = r"(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?\\s*[x×]\\s*" \
        r"(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?\\s*[x×]\\s*" \
        r"(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?"
    if keyword:
        pattern = rf"{keyword}\\s*{pattern}"
    match = re.search(pattern, prompt.lower())
    if not match:
        return None
    a, a_unit, b, b_unit, c, c_unit = match.groups()
    return (
        _to_mm(float(a), a_unit or "mm"),
        _to_mm(float(b), b_unit or "mm"),
        _to_mm(float(c), c_unit or "mm"),
    )


def _parse_pair(prompt: str, keyword: str) -> Optional[Tuple[float, float]]:
    pattern = rf"{keyword}\\s*(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?\\s*[x×]\\s*" \
        r"(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?"
    match = re.search(pattern, prompt.lower())
    if not match:
        return None
    a, a_unit, b, b_unit = match.groups()
    return (
        _to_mm(float(a), a_unit or "mm"),
        _to_mm(float(b), b_unit or "mm"),
    )


def _parse_value(prompt: str, keyword: str) -> Optional[float]:
    pattern = rf"{keyword}\\s*(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?"
    match = re.search(pattern, prompt.lower())
    if not match:
        return None
    value, unit = match.groups()
    return _to_mm(float(value), unit or "mm")


def _parse_angle(prompt: str) -> Optional[float]:
    match = re.search(r"(\\d+(?:\\.\\d+)?)\\s*(deg|degree|degrees|°)", prompt.lower())
    if not match:
        return None
    value, _ = match.groups()
    return float(value)


def _parse_hole(prompt: str) -> Optional[float]:
    match = re.search(
        r"hole\\s*(?:dia(?:meter)?\\s*)?(\\d+(?:\\.\\d+)?)\\s*(mm|cm|in|inch|inches)?",
        prompt.lower(),
    )
    if not match:
        return None
    value, unit = match.groups()
    return _to_mm(float(value), unit or "mm")


def _choose_shape(prompt: str) -> str:
    prompt = prompt.lower()
    if any(word in prompt for word in ("stand", "holder")):
        return "stand"
    if any(word in prompt for word in ("cylinder", "tube", "pipe", "rod")):
        return "cylinder"
    if any(word in prompt for word in ("sphere", "ball")):
        return "sphere"
    return "box"


def _boolean_engine() -> Optional[str]:
    available = set()
    try:
        available = set(trimesh.boolean.engines_available)
    except Exception:
        available = set()
    for engine in ("manifold", "blender", "scad", "cork"):
        if engine in available:
            return engine
    return None


def _apply_hollow(mesh: trimesh.Trimesh, inner: trimesh.Trimesh, notes: List[str]) -> trimesh.Trimesh:
    engine = _boolean_engine()
    if not engine:
        notes.append("Hollow requested but boolean engine unavailable.")
        return mesh
    try:
        result = trimesh.boolean.difference([mesh, inner], engine=engine)
        if isinstance(result, list):
            return trimesh.util.concatenate(result)
        return result
    except Exception:
        notes.append("Hollow boolean failed; using solid.")
        return mesh


def _apply_subtract(mesh: trimesh.Trimesh, cutter: trimesh.Trimesh, notes: List[str]) -> trimesh.Trimesh:
    engine = _boolean_engine()
    if not engine:
        notes.append("Cutout requested but boolean engine unavailable.")
        return mesh
    try:
        result = trimesh.boolean.difference([mesh, cutter], engine=engine)
        if isinstance(result, list):
            return trimesh.util.concatenate(result)
        return result
    except Exception:
        notes.append("Cutout boolean failed; using solid.")
        return mesh


def _apply_union(meshes: List[trimesh.Trimesh], notes: List[str]) -> trimesh.Trimesh:
    engine = _boolean_engine()
    if not engine:
        return trimesh.util.concatenate(meshes)
    try:
        result = trimesh.boolean.union(meshes, engine=engine)
        if isinstance(result, list):
            return trimesh.util.concatenate(result)
        return result
    except Exception:
        notes.append("Union failed; using merged meshes.")
        return trimesh.util.concatenate(meshes)


def _box_dimensions_mm(numbers: List[Tuple[float, str]]) -> Tuple[float, float, float]:
    values = [_to_mm(val, unit) for val, unit in numbers]
    if len(values) >= 3:
        return values[0], values[1], values[2]
    if len(values) == 2:
        return values[0], values[1], min(values)
    if len(values) == 1:
        return values[0], values[0], values[0]
    return 80.0, 40.0, 20.0


def _cylinder_dimensions_mm(numbers: List[Tuple[float, str]], prompt: str) -> Tuple[float, float, float]:
    values = [_to_mm(val, unit) for val, unit in numbers]
    prompt_lower = prompt.lower()
    height = 50.0
    radius = 20.0
    if values:
        if "radius" in prompt_lower:
            radius = values[0]
            if len(values) > 1:
                height = values[1]
        elif "diameter" in prompt_lower or "dia" in prompt_lower:
            radius = values[0] / 2.0
            if len(values) > 1:
                height = values[1]
        elif len(values) >= 2:
            radius = values[0] / 2.0
            height = values[1]
        else:
            radius = values[0] / 2.0
    diameter = radius * 2.0
    return diameter, diameter, height


def _sphere_dimensions_mm(numbers: List[Tuple[float, str]]) -> Tuple[float, float, float]:
    values = [_to_mm(val, unit) for val, unit in numbers]
    if values:
        diameter = values[0]
        return diameter, diameter, diameter
    return 50.0, 50.0, 50.0


def _apply_fillet(mesh: trimesh.Trimesh, fillet_mm: float) -> trimesh.Trimesh:
    if fillet_mm <= 0:
        return mesh
    mesh = mesh.subdivide()
    iterations = min(30, max(6, int(fillet_mm * 2)))
    try:
        trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=iterations)
    except ModuleNotFoundError:
        return mesh
    return mesh


def _build_stand(prompt: str, notes: List[str]) -> Tuple[trimesh.Trimesh, Tuple[float, float, float]]:
    base_dims = _parse_triplet(prompt, "base") or (120.0, 70.0, 6.0)
    back_dims = _parse_triplet(prompt, "back") or (base_dims[0], 70.0, 4.0)
    angle = _parse_angle(prompt) or 65.0

    base_length, base_depth, base_thickness = base_dims
    back_length, back_height, back_thickness = back_dims

    base = trimesh.creation.box(extents=(base_length, base_depth, base_thickness))
    base.apply_translation((0, 0, base_thickness / 2.0))

    back = trimesh.creation.box(extents=(back_length, back_thickness, back_height))
    back_center = (
        0,
        base_depth / 2.0 - back_thickness / 2.0,
        base_thickness + back_height / 2.0,
    )
    back.apply_translation(back_center)
    pivot = (0, base_depth / 2.0 - back_thickness / 2.0, base_thickness)
    back.apply_transform(
        trimesh.transformations.rotation_matrix(
            angle=-angle * (3.141592653589793 / 180.0),
            direction=(1, 0, 0),
            point=pivot,
        )
    )

    mesh = _apply_union([base, back], notes)
    dimensions = (base_length, base_depth, base_thickness + back_height)
    return mesh, dimensions


def generate_parametric_model(prompt: str) -> ParametricResult:
    shape = _choose_shape(prompt)
    numbers = _extract_numbers(prompt)
    notes: List[str] = []

    wall_thickness = _parse_value(prompt, "wall") or _parse_value(prompt, "thickness")
    hollow = "hollow" in prompt.lower()
    fillet = _parse_value(prompt, "fillet") or _parse_value(prompt, "rounded") or 0.0
    hole_diameter = _parse_hole(prompt)
    slot_pair = _parse_pair(prompt, "slot") or _parse_pair(prompt, "cutout")

    if shape == "stand":
        mesh, dimensions_mm = _build_stand(prompt, notes)
    elif shape == "cylinder":
        diameter_mm, _, height_mm = _cylinder_dimensions_mm(numbers, prompt)
        radius_mm = diameter_mm / 2.0
        mesh = trimesh.creation.cylinder(radius=radius_mm, height=height_mm, sections=96)
        dimensions_mm = (diameter_mm, diameter_mm, height_mm)
        if hollow or wall_thickness:
            thickness = wall_thickness or 2.0
            inner_radius = radius_mm - thickness
            if inner_radius > 1:
                inner = trimesh.creation.cylinder(
                    radius=inner_radius,
                    height=max(1.0, height_mm - thickness * 2.0),
                    sections=64,
                )
                mesh = _apply_hollow(mesh, inner, notes)
        if hole_diameter and hole_diameter < diameter_mm:
            cutter = trimesh.creation.cylinder(
                radius=hole_diameter / 2.0,
                height=height_mm * 1.2,
                sections=48,
            )
            mesh = _apply_subtract(mesh, cutter, notes)
    elif shape == "sphere":
        diameter_mm, _, _ = _sphere_dimensions_mm(numbers)
        mesh = trimesh.creation.icosphere(radius=diameter_mm / 2.0, subdivisions=3)
        dimensions_mm = (diameter_mm, diameter_mm, diameter_mm)
        if hollow or wall_thickness:
            thickness = wall_thickness or 2.0
            inner_radius = diameter_mm / 2.0 - thickness
            if inner_radius > 1:
                inner = trimesh.creation.icosphere(radius=inner_radius, subdivisions=3)
                mesh = _apply_hollow(mesh, inner, notes)
    else:
        dims = _parse_triplet(prompt, "size")
        length_mm, width_mm, height_mm = dims or _box_dimensions_mm(numbers)
        mesh = trimesh.creation.box(extents=(length_mm, width_mm, height_mm))
        dimensions_mm = (length_mm, width_mm, height_mm)
        if hollow or wall_thickness:
            thickness = wall_thickness or 2.0
            inner_dims = (
                max(1.0, length_mm - thickness * 2.0),
                max(1.0, width_mm - thickness * 2.0),
                max(1.0, height_mm - thickness * 2.0),
            )
            inner = trimesh.creation.box(extents=inner_dims)
            mesh = _apply_hollow(mesh, inner, notes)
        if hole_diameter and hole_diameter < min(length_mm, width_mm):
            cutter = trimesh.creation.cylinder(
                radius=hole_diameter / 2.0,
                height=height_mm * 1.2,
                sections=48,
            )
            mesh = _apply_subtract(mesh, cutter, notes)
        if slot_pair:
            slot_length, slot_width = slot_pair
            cutter = trimesh.creation.box(
                extents=(slot_length, slot_width, height_mm * 1.2)
            )
            mesh = _apply_subtract(mesh, cutter, notes)

    if fillet > 0:
        mesh = _apply_fillet(mesh, fillet)

    job_id = uuid.uuid4().hex
    job_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    glb_path = job_dir / "model.glb"

    glb_bytes = trimesh.Scene(mesh).export(file_type="glb")
    glb_path.write_bytes(glb_bytes)

    return ParametricResult(
        job_id=job_id,
        glb_path=glb_path,
        shape=shape,
        dimensions_mm=dimensions_mm,
        notes=notes,
    )
