from __future__ import annotations

from services.codegen.models import Build, Design, DesignParameter
from services.spec_compliance import (
    evaluate_spec_compliance,
    extract_explicit_requirements,
    record_parameter_targets,
    record_spec_targets,
)


def _design(*parameters: DesignParameter, template_id: str = "simple_box") -> Design:
    return Design(
        id="a" * 32,
        revision_id="rev",
        name="Compliance fixture",
        script="result = None",
        parameters=list(parameters),
        metadata={"template_id": template_id},
    )


def test_polish_triplet_and_open_top_are_explicit_contracts() -> None:
    design = _design(
        DesignParameter(name="width", value=80.0),
        DesignParameter(name="depth", value=60.0),
        DesignParameter(name="height", value=30.0),
        DesignParameter(name="wall_thickness", value=3.0),
        DesignParameter(name="open_top", value=True, type="boolean"),
    )
    prompt = "pudełko 80x60x30 mm, otwarte od góry, grubość ścianki 3 mm"

    requirements = extract_explicit_requirements(prompt, design.parameters)

    assert {requirement.parameter: requirement.expected for requirement in requirements} == {
        "width": 80.0,
        "depth": 60.0,
        "height": 30.0,
        "wall_thickness": 3.0,
        "open_top": True,
    }


def test_parameter_and_geometry_compliance_pass_together() -> None:
    design = _design(
        DesignParameter(name="width", value=80.0),
        DesignParameter(name="depth", value=60.0),
        DesignParameter(name="height", value=30.0),
    )
    build = Build(revision_id="rev", mesh_hash="mesh", bounding_box_mm=(80.0, 60.0, 30.0))

    report = evaluate_spec_compliance(design, build, "box 80x60x30 mm")

    assert report["status"] == "passed"
    assert len(report["checks"]) == 6
    assert all(check["passed"] for check in report["checks"])


def test_mismatch_returns_deterministic_parameter_repair() -> None:
    design = _design(DesignParameter(name="height", value=30.0))

    report = evaluate_spec_compliance(design, None, "change height to 35 mm")

    assert report["status"] == "needs_repair"
    assert report["repair_parameters"] == [{"name": "height", "new_value": 35.0}]


def test_hamster_wheel_units_counts_and_geometry_are_verified() -> None:
    design = _design(
        DesignParameter(name="wheel_diameter", value=120.0),
        DesignParameter(name="track_width", value=40.0),
        DesignParameter(name="rung_count", value=24, type="count"),
        DesignParameter(name="base_length", value=90.0),
        template_id="hamster_wheel",
    )
    build = Build(revision_id="rev", mesh_hash="mesh", bounding_box_mm=(120.0, 55.0, 128.0))

    report = evaluate_spec_compliance(
        design,
        build,
        "kołowrotek średnica 12 cm, szerokość bieżnika 4 cm, dokładnie 24 szczebelki",
    )

    assert report["status"] == "passed"
    assert {check["name"] for check in report["checks"]} >= {
        "wheel_diameter",
        "track_width",
        "rung_count",
        "wheel_outer_extent",
    }


def test_later_edits_replace_only_the_changed_requirement() -> None:
    design = _design(
        DesignParameter(name="width", value=80.0),
        DesignParameter(name="depth", value=60.0),
        DesignParameter(name="height", value=30.0),
    )
    assert record_spec_targets(design, "box 80x60x30 mm")
    design.parameters[2].value = 35.0
    assert record_parameter_targets(design, {"height": 35.0}, source="change height to 35 mm")
    build = Build(revision_id="rev", mesh_hash="mesh", bounding_box_mm=(80.0, 60.0, 35.0))

    report = evaluate_spec_compliance(design, build)

    assert report["status"] == "passed"
    targets = {check["name"]: check["expected"] for check in report["checks"] if check["kind"] == "parameter"}
    assert targets == {"width": 80.0, "depth": 60.0, "height": 35.0}
