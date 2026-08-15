from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
from typing import Any

import httpx
import contourpy
import numpy as np
from PIL import Image
from scipy import ndimage
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from config import settings


@dataclass
class JewelryTrace:
    script: str
    metadata: dict[str, Any]
    polygons: list[dict[str, Any]]
    svg_path: str
    view_box: list[float]


def trace_jewelry_image_to_script(
    image_bytes: bytes,
    *,
    reference_mm: float,
    reference_label: str = "overall width",
    context: str = "Freeform jewelry",
    brief: str = "",
    profile_id: str = "resin_print",
    trace_mode: str = "auto",
    detail: str = "medium",
) -> JewelryTrace:
    preview = preview_jewelry_trace(
        image_bytes,
        reference_mm=reference_mm,
        reference_label=reference_label,
        context=context,
        trace_mode=trace_mode,
        detail=detail,
    )
    trace_payload = _trace_payload(preview, brief=brief, profile_id=profile_id)
    return trace_preview_to_script(trace_payload)


def jewelry_profile_catalog() -> dict[str, Any]:
    profiles = [
        {
            "id": "resin_print",
            "label": "Resin print",
            "build_intent": "resin_print",
            "min_width_mm": 0.8,
            "min_cutout_mm": 0.6,
            "base_thickness_mm": 2.0,
            "relief_height_mm": 0.8,
            "engraving_depth_mm": 0.35,
            "bail_thickness_mm": 2.0,
        },
        {
            "id": "silver_casting",
            "label": "Silver casting",
            "build_intent": "casting",
            "min_width_mm": 1.1,
            "min_cutout_mm": 0.8,
            "base_thickness_mm": 1.8,
            "relief_height_mm": 0.7,
            "engraving_depth_mm": 0.25,
            "bail_thickness_mm": 2.4,
        },
        {
            "id": "brass_casting",
            "label": "Brass casting",
            "build_intent": "casting",
            "min_width_mm": 1.2,
            "min_cutout_mm": 0.9,
            "base_thickness_mm": 2.0,
            "relief_height_mm": 0.8,
            "engraving_depth_mm": 0.25,
            "bail_thickness_mm": 2.6,
        },
        {
            "id": "laser_acrylic",
            "label": "Laser cut acrylic",
            "build_intent": "laser_cut",
            "min_width_mm": 1.5,
            "min_cutout_mm": 1.2,
            "base_thickness_mm": 3.0,
            "relief_height_mm": 0.0,
            "engraving_depth_mm": 0.15,
            "bail_thickness_mm": 3.0,
        },
        {
            "id": "fdm_prototype",
            "label": "Generic FDM prototype",
            "build_intent": "resin_print",
            "min_width_mm": 1.8,
            "min_cutout_mm": 1.6,
            "base_thickness_mm": 3.0,
            "relief_height_mm": 1.0,
            "engraving_depth_mm": 0.45,
            "bail_thickness_mm": 3.2,
        },
    ]
    return {
        "profiles": profiles,
        "default": "resin_print",
        "default_profile_id": "resin_print",
        "roles": ["base_metal", "cutout", "raised_relief", "engraving", "ignore"],
        "repairs": [
            {"id": "close_gaps", "label": "Close gaps"},
            {"id": "remove_specks", "label": "Remove specks"},
            {"id": "widen_bridges", "label": "Widen bridges"},
            {"id": "merge_tiny_islands", "label": "Merge tiny islands"},
            {"id": "smooth_spikes", "label": "Smooth spikes"},
        ],
    }


def _profile(profile_id: str | None) -> dict[str, Any]:
    catalog = jewelry_profile_catalog()
    return next(
        (p for p in catalog["profiles"] if p["id"] == profile_id),
        next(p for p in catalog["profiles"] if p["id"] == "resin_print"),
    )


async def generate_jewelry_concepts(
    *,
    prompt: str,
    context: str = "Pendant",
    profile_id: str = "resin_print",
    count: int = 3,
    openai_api_key: str | None = None,
) -> dict[str, Any]:
    if not openai_api_key and not settings.allow_platform_ai_spend:
        return {
            "configured": False,
            "profile_id": profile_id,
            "concepts": [],
            "message": "Platform-paid image generation is disabled.",
        }
    api_key = openai_api_key or settings.openai_api_key
    if not api_key:
        return {
            "configured": False,
            "profile_id": profile_id,
            "concepts": [],
            "message": "OPENAI_API_KEY is not configured.",
        }

    profile = _profile(profile_id)
    concepts = []
    variants = [
        "balanced and elegant",
        "organic with strong connected branches",
        "geometric with stable negative space",
        "minimal luxury silhouette",
    ]
    async with httpx.AsyncClient(timeout=120) as client:
        for idx in range(max(1, min(count, 4))):
            concept_prompt = (
                f"Create a CAD-trace-friendly black and white {context.lower()} jewelry concept. "
                f"Brief: {prompt}. Variant: {variants[idx % len(variants)]}. "
                "Use pure white for metal and pure black for cutouts/background. "
                "Flat orthographic front view only. No shadows, gradients, perspective, text, gems, chains, skin, or texture. "
                "All white metal regions should be connected unless intentionally separate paired earrings. "
                f"Minimum visible bridge width should respect {profile['min_width_mm']} mm. "
                "Use closed clean shapes suitable for vector tracing, relief CAD, resin printing, casting, or laser cutting."
            )
            response = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.openai_image_model,
                    "prompt": concept_prompt,
                    "size": "1024x1024",
                    "quality": "medium",
                    "n": 1,
                },
            )
            if response.status_code >= 400:
                raise ValueError(f"OpenAI image generation failed: {response.text[:240]}")
            data = (response.json().get("data") or [{}])[0]
            image_url = data.get("url") or ""
            if data.get("b64_json"):
                image_url = f"data:image/png;base64,{data['b64_json']}"
            concepts.append(
                {
                    "id": f"concept_{idx + 1}",
                    "image_url": image_url,
                    "prompt": concept_prompt,
                    "score": None,
                    "score_reasons": ["Trace scoring runs after selecting the concept."],
                }
            )
    return {"configured": True, "profile_id": profile_id, "concepts": concepts}


def trace_jewelry_image_preview(
    image_bytes: bytes,
    *,
    reference_mm: float,
    reference_label: str = "overall width",
    context: str = "Freeform jewelry",
    brief: str = "",
    profile_id: str = "resin_print",
    repairs: list[str] | None = None,
    trace_mode: str = "auto",
    detail: str = "medium",
) -> dict[str, Any]:
    if repairs and any(r in {"close_gaps", "widen_bridges", "merge_tiny_islands"} for r in repairs):
        detail = "bold"
    elif repairs and "smooth_spikes" in repairs:
        detail = "medium"
    preview = preview_jewelry_trace(
        image_bytes,
        reference_mm=reference_mm,
        reference_label=reference_label,
        context=context,
        trace_mode=trace_mode,
        detail=detail,
    )
    payload = _trace_payload(preview, brief=brief, profile_id=profile_id, repairs=repairs or [])
    return payload


def trace_preview_to_script(trace_payload: dict[str, Any]) -> JewelryTrace:
    contours = [
        contour
        for contour in trace_payload.get("contours", [])
        if contour.get("role") != "ignore" and len(contour.get("points") or []) >= 3
    ]
    polygons = trace_payload.get("polygons") or [
        {"outer": contour["points"], "holes": []}
        for contour in contours
        if contour.get("role") in {"base_metal", "raised_relief"}
    ]
    if not contours and not polygons:
        raise ValueError("Trace payload has no printable contours.")
    reference_mm = float(trace_payload.get("reference_mm") or 40.0)
    reference_label = str(trace_payload.get("reference_label") or "overall width")
    context = str(trace_payload.get("context") or "Freeform jewelry")
    brief = str(trace_payload.get("brief") or "")
    trace_mode = str(trace_payload.get("trace_mode") or "manual_trace")
    image_size = tuple(trace_payload.get("image_size") or [240, 240])
    svg_path = str(trace_payload.get("svg_path") or trace_payload.get("preview_svg") or "")
    view_box = list(trace_payload.get("view_box") or [-20.0, -20.0, 40.0, 40.0])
    profile = _profile(str(trace_payload.get("profile_id") or "resin_print"))
    script = _script_from_semantic_contours(
        contours or [
            {"id": f"trace_{idx + 1}", "role": "base_metal", "points": poly["outer"], "parent_id": None}
            for idx, poly in enumerate(polygons)
        ],
        attachments=trace_payload.get("attachments") or [],
        profile=profile,
        reference_mm=reference_mm,
        reference_label=reference_label,
        context=context,
        brief=brief,
        trace_mode=trace_mode,
    )
    metadata = {
        "template_id": "jewelry_trace",
        "trace_mode": trace_mode,
        "trace_detail": trace_payload.get("trace_detail", "manual"),
        "trace_polygon_count": len(polygons),
        "trace_component_count": len(trace_payload.get("contours") or polygons),
        "trace_reference_mm": reference_mm,
        "trace_reference_label": reference_label,
        "trace_image_size": list(image_size),
        "jewelry_context": context,
        "jewelry_trace": trace_payload,
    }
    return JewelryTrace(
        script=script,
        metadata=metadata,
        polygons=polygons,
        svg_path=svg_path,
        view_box=view_box,
    )


def preview_jewelry_trace(
    image_bytes: bytes,
    *,
    reference_mm: float,
    reference_label: str = "overall width",
    context: str = "Freeform jewelry",
    trace_mode: str = "auto",
    detail: str = "medium",
) -> dict[str, Any]:
    if reference_mm <= 0:
        raise ValueError("reference_mm must be greater than zero.")

    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((240, 240))
    rgb = np.asarray(image)

    masks = _candidate_masks(rgb, trace_mode=trace_mode, detail=detail)
    scored = [_trace_mask(mask, reference_mm, reference_label, detail=detail) for mask in masks]
    scored = [item for item in scored if item is not None]
    if not scored:
        raise ValueError("Could not trace enough contrast from the jewelry image.")

    traced = max(scored, key=lambda item: item["score"])
    polygons = traced["polygons"]
    if not polygons:
        raise ValueError("Could not extract printable jewelry regions from the image.")

    svg_path, view_box = _svg_preview(polygons)
    metadata = {
        "template_id": "jewelry_trace",
        "trace_mode": traced["mode"],
        "trace_detail": detail,
        "trace_polygon_count": len(polygons),
        "trace_component_count": traced["component_count"],
        "trace_reference_mm": reference_mm,
        "trace_reference_label": reference_label,
        "trace_image_size": list(image.size),
        "jewelry_context": context,
    }
    return {
        "polygons": polygons,
        "svg_path": svg_path,
        "view_box": view_box,
        "metadata": metadata,
    }


def _trace_payload(
    preview: dict[str, Any],
    *,
    brief: str = "",
    profile_id: str = "resin_print",
    repairs: list[str] | None = None,
) -> dict[str, Any]:
    metadata = preview["metadata"]
    polygons = preview["polygons"]
    profile = _profile(profile_id)
    contours = []
    warnings = []
    for idx, poly in enumerate(polygons):
        polygon = Polygon(poly["outer"], poly.get("holes") or [])
        contour_id = f"trace_{idx + 1}"
        min_width = _min_width(polygon)
        contours.append(
            {
                "id": contour_id,
                "role": "base_metal",
                "points": poly["outer"],
                "parent_id": None,
                "area_mm2": round(abs(float(polygon.area)), 3),
                "min_width_mm": min_width,
            }
        )
        for hole_idx, hole in enumerate(poly.get("holes") or []):
            hole_poly = Polygon(hole)
            if hole_poly.is_empty:
                continue
            contours.append(
                {
                    "id": f"{contour_id}_cutout_{hole_idx + 1}",
                    "role": "cutout",
                    "points": hole,
                    "parent_id": contour_id,
                    "area_mm2": round(abs(float(hole_poly.area)), 3),
                    "min_width_mm": _min_width(hole_poly),
                }
            )
        if polygon.area < 1.5:
            warnings.append(
                {
                    "severity": "warn",
                    "code": "tiny_region",
                    "contour_id": contour_id,
                    "message": "A traced region is very small and may be noise.",
                    "suggestion": "Use Bold detail or mark the region as ignore in the correction pass.",
                }
            )
        if min_width < float(profile["min_width_mm"]):
            warnings.append(
                {
                    "severity": "warn",
                    "code": "thin_bridge",
                    "contour_id": contour_id,
                    "message": f"A metal region is thinner than {profile['min_width_mm']} mm for {profile['label']}.",
                    "suggestion": "Use Widen bridges, simplify the art, or choose a finer profile.",
                }
            )

    trace_id = f"{metadata['trace_mode']}_{metadata['trace_detail']}_{len(polygons)}"
    graph = _contour_graph(contours)
    disconnected = [node for node in graph["nodes"] if node["disconnected"]]
    if disconnected:
        warnings.append(
            {
                "severity": "warn",
                "code": "disconnected_islands",
                "message": f"{len(disconnected)} separate metal island(s) are not connected to the main piece.",
                "suggestion": "Merge tiny islands, add bridges, or keep them intentionally separate.",
            }
        )
    repairs_map: dict[str, str] = {}
    if any(w["code"] == "tiny_region" for w in warnings):
        repairs_map["remove_specks"] = "Remove specks"
    if any(w["code"] == "thin_bridge" for w in warnings):
        repairs_map["widen_bridges"] = "Widen bridges"
    if disconnected:
        repairs_map["merge_tiny_islands"] = "Merge tiny islands"
    if warnings:
        repairs_map["smooth_spikes"] = "Smooth spikes"
    score = _score_trace(contours, warnings, disconnected)
    return {
        "trace_id": trace_id,
        "context": metadata["jewelry_context"],
        "brief": brief,
        "profile_id": profile_id,
        "profile": profile,
        "build_intent": profile["build_intent"],
        "reference_mm": metadata["trace_reference_mm"],
        "reference_label": metadata["trace_reference_label"],
        "image_size": metadata["trace_image_size"],
        "trace_mode": metadata["trace_mode"],
        "trace_detail": metadata["trace_detail"],
        "trace_polygon_count": metadata["trace_polygon_count"],
        "trace_component_count": metadata["trace_component_count"],
        "polygons": polygons,
        "svg_path": preview["svg_path"],
        "view_box": preview["view_box"],
        "preview_svg": preview["svg_path"],
        "contours": contours,
        "graph": graph,
        "attachments": _default_attachments(contours, metadata["jewelry_context"], profile),
        "warnings": warnings,
        "repair_suggestions": [{"id": key, "label": label} for key, label in repairs_map.items()],
        "score": {
            "value": score,
            "reasons": [
                f"Detected {len([c for c in contours if c['role'] == 'base_metal'])} metal region(s).",
                f"Trace mode: {metadata['trace_mode']}, detail: {metadata['trace_detail']}.",
                "Connected silhouette." if not disconnected else f"{len(disconnected)} disconnected island(s).",
            ],
        },
        "repairs": repairs or [],
    }


def _candidate_masks(rgb: np.ndarray, *, trace_mode: str, detail: str) -> list[tuple[str, np.ndarray]]:
    mx = rgb.max(axis=2).astype(np.int16)
    mn = rgb.min(axis=2).astype(np.int16)
    sat = mx - mn
    bright_threshold = max(145, int(np.percentile(mx, 72)))
    silver_detail_threshold = max(136, int(np.percentile(mn, 90)))
    silver_strict_threshold = max(148, int(np.percentile(mn, 94)))
    bright = (mn >= silver_detail_threshold) & (mx >= bright_threshold) & (sat <= 95)
    silver_strict = (mn >= silver_strict_threshold) & (sat <= 85)
    dark_threshold = min(105, int(np.percentile(mx, 28)))
    dark = mx <= dark_threshold

    close_sizes = {
        "fine": (2, 5, 2),
        "medium": (3, 9, 3),
        "bold": (5, 13, 5),
    }.get(detail, (3, 9, 3))
    all_candidates = (
        ("bright_metal", bright, close_sizes[0]),
        ("bright_metal_connected", silver_strict, close_sizes[1]),
        ("dark_ink", dark, close_sizes[2]),
    )
    if trace_mode == "auto":
        candidates = all_candidates[:2]
    else:
        candidates = tuple(item for item in all_candidates if item[0] == trace_mode)
    if not candidates:
        candidates = (("bright_metal_connected", silver_strict, close_sizes[1]),)

    cleaned: list[tuple[str, np.ndarray]] = []
    for mode, mask, close_size in candidates:
        mask = ndimage.binary_opening(mask, structure=np.ones((2, 2), dtype=bool))
        mask = ndimage.binary_closing(mask, structure=np.ones((close_size, close_size), dtype=bool))
        mask = ndimage.binary_fill_holes(mask)
        cleaned.append((mode, mask))
    return cleaned


def _trace_mask(
    mode_and_mask: tuple[str, np.ndarray],
    reference_mm: float,
    reference_label: str,
    *,
    detail: str,
) -> dict[str, Any] | None:
    mode, mask = mode_and_mask
    labeled, count = ndimage.label(mask)
    if count == 0:
        return None

    components: list[dict[str, Any]] = []
    image_h, image_w = mask.shape
    for idx in range(1, count + 1):
        ys, xs = np.where(labeled == idx)
        area = int(xs.size)
        if area < 18:
            continue
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        bbox_area = max((x1 - x0) * (y1 - y0), 1)
        fill = area / bbox_area
        if fill > 0.92 and area > image_w * image_h * 0.2:
            continue
        touches_edge = x0 <= 1 or y0 <= 1 or x1 >= image_w - 1 or y1 >= image_h - 1
        if touches_edge and area > image_w * image_h * 0.03:
            continue
        components.append(
            {
                "idx": idx,
                "area": area,
                "bbox": (x0, y0, x1, y1),
                "center": (float(xs.mean()), float(ys.mean())),
            }
        )
    if not components:
        return None

    components.sort(key=lambda item: item["area"], reverse=True)
    anchor = components[0]
    ax0, ay0, ax1, ay1 = anchor["bbox"]
    pad_x = max(image_w * 0.18, (ax1 - ax0) * 0.65)
    pad_y = max(image_h * 0.18, (ay1 - ay0) * 0.65)
    largest = anchor["area"]
    selected: list[dict[str, Any]] = []
    for comp in components:
        cx, cy = comp["center"]
        near_anchor = ax0 - pad_x <= cx <= ax1 + pad_x and ay0 - pad_y <= cy <= ay1 + pad_y
        if comp["area"] >= max(18, largest * 0.025) and near_anchor:
            selected.append(comp)
    selected = selected[:18]
    if not selected:
        return None

    ys_all: list[np.ndarray] = []
    xs_all: list[np.ndarray] = []
    for comp in selected:
        ys, xs = np.where(labeled == comp["idx"])
        ys_all.append(ys)
        xs_all.append(xs)
    xs_cat = np.concatenate(xs_all)
    ys_cat = np.concatenate(ys_all)
    min_x, max_x = int(xs_cat.min()), int(xs_cat.max()) + 1
    min_y, max_y = int(ys_cat.min()), int(ys_cat.max()) + 1
    width_px = max(max_x - min_x, 1)
    height_px = max(max_y - min_y, 1)
    use_height = any(word in reference_label.lower() for word in ("height", "tall", "length"))
    px_to_mm = reference_mm / (height_px if use_height else width_px)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    selected_ids = {int(comp["idx"]) for comp in selected}
    selected_mask = np.isin(labeled, list(selected_ids))
    geom = _contour_geometry(selected_mask, center_x, center_y, px_to_mm)
    if geom is None or geom.is_empty:
        shapes = []
        for comp in selected:
            shapes.extend(_row_run_boxes(labeled == comp["idx"], center_x, center_y, px_to_mm))
        geom = unary_union(shapes) if shapes else None
    if geom is None or geom.is_empty:
        return None

    smooth_factor = {"fine": 0.35, "medium": 0.65, "bold": 0.9}.get(detail, 0.65)
    geom = geom.buffer(px_to_mm * 0.2).buffer(-px_to_mm * 0.18)
    geom = geom.simplify(max(0.035, px_to_mm * smooth_factor * 0.22), preserve_topology=True)
    polygons = _polygon_payloads(geom)
    if not polygons:
        return None

    selected_area = sum(comp["area"] for comp in selected)
    center_score = 1.0 - min(
        1.0,
        abs(float(xs_cat.mean()) - image_w / 2) / max(image_w / 2, 1)
        + abs(float(ys_cat.mean()) - image_h / 2) / max(image_h / 2, 1),
    ) * 0.35
    mode_boost = 1.25 if mode == "bright_metal_connected" else 1.15 if mode == "bright_metal" else 1.0
    return {
        "mode": mode,
        "score": selected_area * center_score * mode_boost,
        "polygons": polygons,
        "component_count": len(selected),
    }


def _contour_geometry(mask: np.ndarray, center_x: float, center_y: float, px_to_mm: float) -> Polygon | MultiPolygon | None:
    padded = np.pad(mask.astype(float), 1, mode="constant", constant_values=0.0)
    generator = contourpy.contour_generator(z=padded, name="serial", corner_mask=False)
    lines = generator.lines(0.5)
    rings: list[Polygon] = []
    for line in lines:
        if len(line) < 4:
            continue
        # Remove the padding offset. contourpy returns x/y pixel-space points.
        pts = [(float(x) - 1.0, float(y) - 1.0) for x, y in line]
        if np.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1.5:
            continue
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area < 4.0:
            continue
        rings.append(poly)
    if not rings:
        return None

    metal_rings: list[Polygon] = []
    hole_rings: list[Polygon] = []
    h, w = mask.shape
    for ring in rings:
        point = ring.representative_point()
        sx = min(max(int(round(point.x)), 0), w - 1)
        sy = min(max(int(round(point.y)), 0), h - 1)
        if mask[sy, sx]:
            metal_rings.append(ring)
        else:
            hole_rings.append(ring)
    if not metal_rings:
        return None

    geom = unary_union(metal_rings)
    if hole_rings:
        geom = geom.difference(unary_union(hole_rings))
    if geom.is_empty:
        return None
    return affinity.affine_transform(
        geom,
        [px_to_mm, 0.0, 0.0, -px_to_mm, -center_x * px_to_mm, center_y * px_to_mm],
    )


def _row_run_boxes(mask: np.ndarray, center_x: float, center_y: float, px_to_mm: float) -> list[Polygon]:
    boxes: list[Polygon] = []
    h, _ = mask.shape
    for y in range(h):
        xs = np.flatnonzero(mask[y])
        if xs.size == 0:
            continue
        starts = [int(xs[0])]
        ends: list[int] = []
        for prev, cur in zip(xs[:-1], xs[1:]):
            if int(cur) != int(prev) + 1:
                ends.append(int(prev) + 1)
                starts.append(int(cur))
        ends.append(int(xs[-1]) + 1)
        for x0, x1 in zip(starts, ends):
            boxes.append(
                box(
                    (x0 - center_x) * px_to_mm,
                    (center_y - (y + 1)) * px_to_mm,
                    (x1 - center_x) * px_to_mm,
                    (center_y - y) * px_to_mm,
                )
            )
    return boxes


def _polygon_payloads(geom: Polygon | MultiPolygon) -> list[dict[str, list[list[float]]]]:
    geoms = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    payloads: list[dict[str, list[list[float]]]] = []
    for poly in geoms:
        if poly.is_empty or poly.area < 1.0:
            continue
        if not poly.is_valid:
            poly = poly.buffer(0)
        exterior = _coords(poly.exterior.coords)
        holes = [_coords(ring.coords) for ring in poly.interiors if Polygon(ring).area > 0.6]
        if len(exterior) >= 3:
            payloads.append({"outer": exterior, "holes": holes})
    payloads.sort(key=lambda item: abs(Polygon(item["outer"], item["holes"]).area), reverse=True)
    return payloads[:20]


def _coords(coords: Any) -> list[list[float]]:
    return [[round(float(x), 3), round(float(y), 3)] for x, y in list(coords)[:-1]]


def _min_width(poly: Polygon) -> float:
    minx, miny, maxx, maxy = poly.bounds
    return round(float(max(0.0, min(maxx - minx, maxy - miny))), 3)


def _contour_graph(contours: list[dict[str, Any]]) -> dict[str, Any]:
    bases = [c for c in contours if c["role"] == "base_metal"]
    largest_id = bases[0]["id"] if bases else None
    nodes = []
    for contour in contours:
        children = [c["id"] for c in contours if c.get("parent_id") == contour["id"]]
        nodes.append(
            {
                "id": contour["id"],
                "role": contour["role"],
                "parent_id": contour.get("parent_id"),
                "children": children,
                "disconnected": contour["role"] == "base_metal" and contour["id"] != largest_id,
                "min_width_mm": contour.get("min_width_mm"),
                "area_mm2": contour.get("area_mm2"),
            }
        )
    edges = []
    for idx, left in enumerate(contours):
        try:
            left_poly = Polygon(left["points"])
        except Exception:
            continue
        for right in contours[idx + 1 :]:
            try:
                right_poly = Polygon(right["points"])
            except Exception:
                continue
            dist = float(left_poly.distance(right_poly))
            if dist <= 2.0:
                edges.append({"from": left["id"], "to": right["id"], "type": "adjacent", "distance_mm": round(dist, 3)})
    return {"nodes": nodes, "edges": edges}


def _default_attachments(
    contours: list[dict[str, Any]],
    context: str,
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    if "ring" in context.lower():
        return []
    bases = [c for c in contours if c["role"] == "base_metal"]
    if not bases:
        return []
    anchor = max(bases, key=lambda c: float(c.get("area_mm2") or 0))
    bail = float(profile.get("bail_thickness_mm") or 2.0)
    return [
        {
            "id": "top_bail",
            "type": "bail",
            "anchor_contour_id": anchor["id"],
            "position_uv": [0.5, 0.0],
            "outer_diameter_mm": round(bail * 2.6, 2),
            "hole_diameter_mm": round(max(bail * 1.15, 1.4), 2),
            "thickness_mm": bail,
        }
    ]


def _score_trace(
    contours: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    disconnected: list[dict[str, Any]],
) -> int:
    score = 100
    score -= min(35, len(disconnected) * 8)
    score -= min(35, len(warnings) * 7)
    if not any(c["role"] == "base_metal" for c in contours):
        score -= 40
    return max(0, min(100, score))


def _svg_preview(polygons: list[dict[str, Any]]) -> tuple[str, list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    parts: list[str] = []
    for item in polygons:
        rings = [item["outer"], *(item.get("holes") or [])]
        for ring in rings:
            if not ring:
                continue
            xs.extend(float(pt[0]) for pt in ring)
            ys.extend(float(pt[1]) for pt in ring)
            first = ring[0]
            commands = [f"M {float(first[0]):.3f} {float(first[1]):.3f}"]
            commands.extend(f"L {float(x):.3f} {float(y):.3f}" for x, y in ring[1:])
            commands.append("Z")
            parts.append(" ".join(commands))
    if not xs or not ys:
        return "", [-10.0, -10.0, 20.0, 20.0]
    pad = max(max(xs) - min(xs), max(ys) - min(ys), 1.0) * 0.06
    return " ".join(parts), [
        round(min(xs) - pad, 3),
        round(min(ys) - pad, 3),
        round(max(xs) - min(xs) + 2 * pad, 3),
        round(max(ys) - min(ys) + 2 * pad, 3),
    ]


def _script_from_semantic_contours(
    contours: list[dict[str, Any]],
    *,
    attachments: list[dict[str, Any]],
    profile: dict[str, Any],
    reference_mm: float,
    reference_label: str,
    context: str,
    brief: str,
    trace_mode: str,
) -> str:
    contours_json = repr(contours)
    attachments_json = repr(attachments)
    profile_json = repr(profile)
    return f'''\
"""Semantic jewelry trace.

The 2D trace is the source of truth. Contour roles map to base metal,
cutouts, raised relief, engraving, or ignored regions.
"""
import trimesh
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely import affinity
from pulsai import param

TRACE_CONTOURS = {contours_json}
TRACE_ATTACHMENTS = {attachments_json}
JEWELRY_PROFILE = {profile_json}
TRACE_CONTEXT = {context!r}
TRACE_BRIEF = {brief!r}
TRACE_REFERENCE_LABEL = {reference_label!r}
TRACE_REFERENCE_MM = {reference_mm:.4f}
TRACE_MODE = {trace_mode!r}

scale = param("scale", 1.0, type="ratio", min=0.2, max=4.0,
              doc="Uniform scale applied to the traced jewelry paths.")
thickness = param("thickness", JEWELRY_PROFILE["base_thickness_mm"], type="length_mm", min=0.6, max=8.0,
                  doc="Base metal thickness.")
relief_height = param("relief_height", JEWELRY_PROFILE.get("relief_height_mm", 0.8), type="length_mm", min=0.0, max=4.0,
                      doc="Height added for raised relief contours.")
engraving_depth = param("engraving_depth", JEWELRY_PROFILE.get("engraving_depth_mm", 0.3), type="length_mm", min=0.0, max=2.0,
                        doc="Width/depth hint for engraving paths.")
bail_scale = param("bail_scale", 1.0, type="ratio", min=0.4, max=2.5,
                   doc="Scale for bail / connector attachments.")

def _poly(contour):
    poly = Polygon(contour["points"])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if scale != 1.0:
        poly = affinity.scale(poly, xfact=scale, yfact=scale, origin=(0, 0))
    return poly

def _extrude(poly, height, z=0.0):
    if poly.geom_type == "MultiPolygon":
        parts = [_extrude(part, height, z=z) for part in poly.geoms if not part.is_empty and part.area > 0]
        parts = [part for part in parts if part is not None]
        return trimesh.util.concatenate(parts) if parts else None
    if poly.is_empty or poly.area <= 0:
        return None
    mesh = trimesh.creation.extrude_polygon(poly, height=max(float(height), 0.01))
    if z:
        mesh.apply_translation((0, 0, z))
    return mesh

# @feature: semantic_layers
base_polys = [_poly(c) for c in TRACE_CONTOURS if c.get("role") == "base_metal"]
cutouts = [_poly(c) for c in TRACE_CONTOURS if c.get("role") == "cutout"]
reliefs = [_poly(c) for c in TRACE_CONTOURS if c.get("role") == "raised_relief"]
engravings = [_poly(c) for c in TRACE_CONTOURS if c.get("role") == "engraving"]
if base_polys:
    base_shape = unary_union(base_polys)
    for cut in cutouts:
        base_shape = base_shape.difference(cut)
else:
    base_shape = Polygon([(-TRACE_REFERENCE_MM / 2, -TRACE_REFERENCE_MM / 4), (TRACE_REFERENCE_MM / 2, -TRACE_REFERENCE_MM / 4), (TRACE_REFERENCE_MM / 2, TRACE_REFERENCE_MM / 4), (-TRACE_REFERENCE_MM / 2, TRACE_REFERENCE_MM / 4)])
meshes = []
base_mesh = _extrude(base_shape, thickness)
if base_mesh is not None:
    meshes.append(base_mesh)
for relief in reliefs:
    relief_mesh = _extrude(relief, relief_height, z=thickness)
    if relief_mesh is not None:
        meshes.append(relief_mesh)
for engraving in engravings:
    engraving_mesh = _extrude(engraving.buffer(max(engraving_depth, 0.12)), max(engraving_depth, 0.08), z=thickness)
    if engraving_mesh is not None:
        meshes.append(engraving_mesh)
# @end

# @feature: attachments
main_contours = [c for c in TRACE_CONTOURS if c.get("role") == "base_metal"]
if main_contours:
    main = max(main_contours, key=lambda c: abs(Polygon(c["points"]).area))
    main_poly = _poly(main)
    minx, miny, maxx, maxy = main_poly.bounds
    for attachment in TRACE_ATTACHMENTS:
        if attachment.get("type") != "bail":
            continue
        outer = float(attachment.get("outer_diameter_mm", JEWELRY_PROFILE.get("bail_thickness_mm", 2.0) * 2.6)) * bail_scale * scale
        hole = float(attachment.get("hole_diameter_mm", JEWELRY_PROFILE.get("bail_thickness_mm", 2.0) * 1.15)) * bail_scale * scale
        u = float(attachment.get("position_uv", [0.5, 0.0])[0])
        cx = minx + (maxx - minx) * u
        cy = maxy + outer * 0.28
        ring = Point(cx, cy).buffer(outer * 0.5, resolution=28).difference(Point(cx, cy).buffer(hole * 0.5, resolution=28))
        neck = Polygon([(cx - outer * 0.22, maxy - outer * 0.05), (cx + outer * 0.22, maxy - outer * 0.05), (cx + outer * 0.18, cy), (cx - outer * 0.18, cy)])
        attachment_mesh = _extrude(unary_union([ring, neck]), thickness)
        if attachment_mesh is not None:
            meshes.append(attachment_mesh)
# @end

# @feature: combine_trace
result_mesh = trimesh.util.concatenate(meshes) if meshes else trimesh.creation.box(extents=(TRACE_REFERENCE_MM, TRACE_REFERENCE_MM * 0.6, thickness))
result_mesh.merge_vertices()
if hasattr(result_mesh, "remove_duplicate_faces"):
    result_mesh.remove_duplicate_faces()
if hasattr(result_mesh, "remove_degenerate_faces"):
    result_mesh.remove_degenerate_faces()
result_mesh.fix_normals()
# @end

result = result_mesh
'''


def _script_from_polygons(
    polygons: list[dict[str, Any]],
    *,
    reference_mm: float,
    reference_label: str,
    context: str,
    brief: str,
    image_size: tuple[int, int],
    trace_mode: str,
) -> str:
    polygon_json = json.dumps(polygons, separators=(",", ":"))
    return f'''\
"""Traced jewelry from sketch/photo.

The image was vector-traced into polygon regions and extruded as a flat
resin/castable jewelry prototype. Keep edits in this script so the traced
organic contours remain the source of truth.
"""
import trimesh
from shapely.geometry import Polygon
from shapely import affinity
from pulsai import param

TRACE_POLYGONS = {polygon_json}
TRACE_CONTEXT = {context!r}
TRACE_BRIEF = {brief!r}
TRACE_REFERENCE_LABEL = {reference_label!r}
TRACE_REFERENCE_MM = {reference_mm:.4f}
TRACE_IMAGE_SIZE = {tuple(image_size)!r}
TRACE_MODE = {trace_mode!r}

scale = param("scale", 1.0, type="ratio", min=0.2, max=4.0,
              doc="Uniform scale applied to the traced jewelry paths.")
thickness = param("thickness", 2.0, type="length_mm", min=0.8, max=8.0,
                  doc="Base metal thickness for resin/castable prototype.")
z_lift = param("z_lift", 0.0, type="length_mm", min=-10.0, max=10.0,
               doc="Move the traced jewelry up/down for export alignment.")

# @feature: traced_solid_regions
meshes = []
for path in TRACE_POLYGONS:
    poly = Polygon(path["outer"], path.get("holes") or [])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area <= 0:
        continue
    if scale != 1.0:
        poly = affinity.scale(poly, xfact=scale, yfact=scale, origin=(0, 0))
    mesh = trimesh.creation.extrude_polygon(poly, height=thickness)
    mesh.apply_translation((0, 0, z_lift))
    meshes.append(mesh)
# @end

# @feature: combine_trace
if meshes:
    result_mesh = trimesh.util.concatenate(meshes)
    result_mesh.merge_vertices()
    if hasattr(result_mesh, "remove_duplicate_faces"):
        result_mesh.remove_duplicate_faces()
    if hasattr(result_mesh, "remove_degenerate_faces"):
        result_mesh.remove_degenerate_faces()
    result_mesh.fix_normals()
else:
    result_mesh = trimesh.creation.box(extents=(TRACE_REFERENCE_MM, TRACE_REFERENCE_MM * 0.6, thickness))
# @end

result = result_mesh
'''
