from __future__ import annotations

from services.codegen.engine import (
    audit_then_run,
    build_from_sandbox_result,
    derive_parameters,
)
from services.codegen.models import Design
from services.codegen.templates import get_seed_script
from services.mechanism_motion import evaluate_mechanism_motion


def test_hamster_wheel_motion_contract_has_separate_node_and_clearance() -> None:
    _, script = get_seed_script("hamster_wheel")
    sandbox = audit_then_run(script=script, targets=["stl", "glb"])
    assert sandbox.ok, sandbox.payload
    design = Design(
        id="b" * 32,
        revision_id="rev",
        name="Wheel",
        script=script,
        parameters=derive_parameters(sandbox.payload),
        metadata={"template_id": "hamster_wheel"},
    )
    build = build_from_sandbox_result(design, sandbox, process="fdm")

    report = evaluate_mechanism_motion(design, build)

    assert report["supported"] is True
    assert report["status"] == "safe"
    assert report["rotating_node"] == "wheel"
    assert report["axis_viewer"] == [0.0, 0.0, 1.0]
    assert report["axle_clearance_mm"] >= 0.25
    assert report["minimum_static_gap_mm"] > 0
    assert all(check["passed"] for check in report["checks"])


def test_non_mechanism_is_explicitly_unsupported() -> None:
    design = Design(
        id="c" * 32,
        revision_id="rev",
        name="Box",
        script="result = None",
    )

    assert evaluate_mechanism_motion(design, None)["status"] == "unsupported"
