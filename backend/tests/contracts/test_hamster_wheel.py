from pathlib import Path

from services.codegen.engine import _coerce_targets, audit_then_run, run_manufacturability
from services.codegen.templates import (
    get_seed_script,
    match_template_id,
    prompt_seed_is_complete,
    seed_for,
)

import trimesh


def test_polish_hamster_wheel_prompt_does_not_fall_back_to_box() -> None:
    template_id, name, _ = seed_for(
        "Kołowrotek dla chomika do akwarium, średnica 12 centymetrów"
    )

    assert template_id == "hamster_wheel"
    assert "wheel" in name.lower()


def test_hamster_wheel_seed_builds_at_requested_default_diameter() -> None:
    _, script = get_seed_script("hamster_wheel")
    result = audit_then_run(script=script, targets=["stl", "glb"])

    assert result.ok, result.payload
    bbox = result.payload["bbox_mm"]
    assert 119.5 <= bbox[0] <= 120.5
    assert bbox[1] >= 30.0
    assert bbox[2] >= 120.0

    glb = trimesh.load(result.payload["artifacts"]["glb"], force="scene")
    glb_extents = glb.bounds[1] - glb.bounds[0]
    assert glb_extents[1] >= 120.0  # glTF preview is Y-up, so the wheel stays upright.
    assert glb_extents[2] < 60.0
    assert {"wheel", "stand", "axle"}.issubset(set(glb.graph.nodes_geometry))


def test_unknown_prompt_is_not_reported_as_a_matched_box() -> None:
    assert match_template_id("ergonomic articulated camera gimbal") is None


def test_glb_only_request_includes_required_stl_mesh() -> None:
    assert _coerce_targets(["glb"]) == ["stl", "glb"]


def test_polish_rung_wheel_prompt_is_fully_parameterized_without_an_agent() -> None:
    prompt = (
        "Kołowrotek dla chomika: średnica 20 cm, szerokość 4 cm, "
        "dokładnie 24 szczebelki."
    )

    template_id, _, script = seed_for(prompt)

    assert template_id == "hamster_wheel"
    assert 'param("wheel_diameter", 200.0' in script
    assert 'param("track_width", 40.0' in script
    assert 'param("rung_count", 24' in script
    assert "# Transverse rungs across the track" in script
    assert "wheel_tread = Compound" in script
    assert "with BuildPart() as wheel:" not in script
    assert prompt_seed_is_complete(prompt, template_id)

    result = audit_then_run(script=script, targets=["stl", "glb"])
    assert result.ok, result.payload
    bbox = result.payload["bbox_mm"]
    assert 199.0 <= bbox[0] <= 203.0
    assert 38.0 <= bbox[1] <= 58.0
    report = run_manufacturability(
        stl_path=Path(result.payload["artifacts"]["stl"]),
        process="fdm",
        printer_profile_id="prusa_mk4_default",
    )
    assert not any(issue.code == "non_watertight" for issue in report.issues)
    assert not any(issue.code == "min_wall_thin" for issue in report.issues)
