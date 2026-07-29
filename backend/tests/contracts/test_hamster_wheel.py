from services.codegen.engine import _coerce_targets, audit_then_run
from services.codegen.templates import get_seed_script, match_template_id, seed_for

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


def test_unknown_prompt_is_not_reported_as_a_matched_box() -> None:
    assert match_template_id("ergonomic articulated camera gimbal") is None


def test_glb_only_request_includes_required_stl_mesh() -> None:
    assert _coerce_targets(["glb"]) == ["stl", "glb"]
