from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from services.codegen.engine import audit_then_run
from services.jewelry_trace import (
    preview_jewelry_trace,
    trace_jewelry_image_preview,
    trace_jewelry_image_to_script,
    trace_preview_to_script,
)


def _synthetic_cross_with_branch() -> bytes:
    image = Image.new("RGB", (180, 220), (26, 26, 26))
    draw = ImageDraw.Draw(image)
    metal = (238, 238, 228)
    draw.rectangle((78, 35, 102, 178), fill=metal)
    draw.rectangle((38, 76, 142, 100), fill=metal)
    draw.ellipse((78, 12, 102, 36), fill=metal)
    draw.ellipse((86, 18, 94, 28), fill=(26, 26, 26))
    draw.line((90, 165, 90, 54), fill=metal, width=7)
    draw.line((90, 84, 54, 66), fill=metal, width=6)
    draw.line((90, 95, 128, 68), fill=metal, width=5)
    draw.line((90, 122, 63, 145), fill=metal, width=5)
    draw.ellipse((49, 60, 61, 72), fill=metal)
    draw.ellipse((122, 62, 134, 74), fill=metal)
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_jewelry_trace_emits_buildable_organic_script() -> None:
    trace = trace_jewelry_image_to_script(
        _synthetic_cross_with_branch(),
        reference_mm=42.0,
        reference_label="overall width",
        context="Pendant",
        brief="cross pendant with tree and flower shapes",
    )

    assert "TRACE_CONTOURS" in trace.script
    assert "Cylindrical holder" not in trace.script
    assert trace.metadata["template_id"] == "jewelry_trace"
    assert trace.metadata["trace_polygon_count"] >= 1
    assert trace.svg_path
    assert len(trace.view_box) == 4

    result = audit_then_run(script=trace.script, targets=["stl", "glb"])
    assert result.ok, result.payload.get("error")
    assert result.payload["bbox_mm"][0] > 30
    assert result.payload["bbox_mm"][2] >= 1.9


def test_jewelry_trace_preview_exposes_modes_for_correction() -> None:
    preview = preview_jewelry_trace(
        _synthetic_cross_with_branch(),
        reference_mm=42.0,
        reference_label="overall width",
        context="Pendant",
        trace_mode="bright_metal_connected",
        detail="bold",
    )

    assert preview["metadata"]["trace_mode"] == "bright_metal_connected"
    assert preview["metadata"]["trace_detail"] == "bold"
    assert preview["svg_path"].startswith("M ")
    assert len(preview["view_box"]) == 4


def test_jewelry_semantic_preview_graph_and_profile_build() -> None:
    preview = trace_jewelry_image_preview(
        _synthetic_cross_with_branch(),
        reference_mm=42.0,
        reference_label="overall width",
        context="Pendant",
        profile_id="silver_casting",
        brief="cross pendant with tree and flower shapes",
    )

    assert preview["profile_id"] == "silver_casting"
    assert preview["build_intent"] == "casting"
    assert preview["contours"]
    assert preview["graph"]["nodes"]
    assert preview["attachments"][0]["type"] == "bail"
    assert isinstance(preview["score"]["value"], int)

    preview["contours"][0]["role"] = "raised_relief"
    trace = trace_preview_to_script(preview)
    assert "raised_relief" in trace.script
    result = audit_then_run(script=trace.script, targets=["stl", "glb"])
    assert result.ok, result.payload.get("error")
