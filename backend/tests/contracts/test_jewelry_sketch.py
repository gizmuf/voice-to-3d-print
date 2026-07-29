from __future__ import annotations

from services.native_converter import structured_spec_to_editable
from services.codegen.templates import seed_for
from services.useful_objects import build_useful_structured_spec


def test_necklace_sketch_routes_to_flexible_jewelry_piece() -> None:
    spec = build_useful_structured_spec(
        "Create flexible jewelry from sketch. Jewelry context: Necklace. "
        "Reference dimension: overall width 120 mm. "
        "Creative brief: large organic necklace with 9 linked flower elements.",
        source="jewelry_sketch",
    )

    assert spec["template_id"] == "jewelry_piece"
    assert spec["dimensions_mm"]["width"] == 120.0
    assert spec["constraints"]["shape_profile"] == "necklace_arc"
    assert spec["constraints"]["attachment_count"] == 9.0

    model = structured_spec_to_editable(spec)
    assert model.manufacturability.status == "safe"
    assert model.bodies[0].params["_object_label"] == "Jewelry piece"


def test_ring_sketch_keeps_ring_specific_sizing() -> None:
    spec = build_useful_structured_spec(
        "Create flexible jewelry from sketch. Jewelry context: Ring. "
        "Reference dimension: inner diameter 18.2 mm. "
        "Creative brief: sculptural signet ring with raised floral detail.",
        source="jewelry_sketch",
    )

    assert spec["template_id"] == "jewelry_ring"
    assert spec["dimensions_mm"]["inner_diameter"] == 18.2

    model = structured_spec_to_editable(spec)
    assert model.bodies[0].children[0].label == "Ring band"


def test_design_seed_does_not_route_jewelry_to_pen_holder() -> None:
    template_id, name, script = seed_for(
        "Design a flexible jewelry piece from an iPad sketch. "
        "Jewelry context: Pendant. Reference dimension: overall width 35 mm. "
        "Creative brief: cross pendant with organic branch openwork."
    )

    assert template_id == "jewelry_cross"
    assert name == "Cross pendant starter"
    assert "Cylindrical holder" not in script


def test_open_ended_jewelry_does_not_match_pen_substring() -> None:
    template_id, name, script = seed_for(
        "Design open-ended jewelry from sketch, with connector openings and raised relief."
    )

    assert template_id == "jewelry_piece"
    assert name == "Jewelry sketch starter"
    assert "Pen / cup" not in script
