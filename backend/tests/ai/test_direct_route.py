from services.ai.direct_route import (
    ambiguity_question,
    parse_direct_parameter_edit,
    parse_direct_parameter_edits,
)
from services.codegen.models import DesignParameter


def _param(name: str, value, type_: str = "length_mm") -> DesignParameter:
    return DesignParameter(name=name, value=value, type=type_, min=0, max=500)


def test_polish_wheel_diameter_converts_centimeters() -> None:
    params = [_param("wheel_diameter", 120.0), _param("axle_diameter", 5.0)]
    edit = parse_direct_parameter_edit("zmień średnicę kołowrotka na 12 centymetrów", params)
    assert edit is not None
    assert (edit.name, edit.value) == ("wheel_diameter", 120.0)


def test_polish_rung_count_is_not_spoke_count() -> None:
    params = [_param("rung_count", 32, "count"), _param("spoke_count", 6, "count")]
    edit = parse_direct_parameter_edit("ustaw dokładnie 24 szczebelki", params)
    assert edit is not None
    assert (edit.name, edit.value) == ("rung_count", 24)


def test_polish_from_to_edit_uses_the_target_value() -> None:
    params = [_param("height", 30.0), _param("width", 80.0)]

    edit = parse_direct_parameter_edit(
        "Zmień wysokość pudełka z 30 mm na 35 mm.",
        params,
    )

    assert edit is not None
    assert (edit.name, edit.value) == ("height", 35.0)


def test_ambiguous_strength_request_requires_question() -> None:
    assert ambiguity_question("zrób ten wspornik bardziej wytrzymały") is not None
    assert ambiguity_question("ustaw grubość na 6 mm") is None


def test_two_explicit_dimensions_are_parsed_as_one_local_batch() -> None:
    params = [
        _param("wheel_diameter", 120.0),
        _param("track_width", 40.0),
        _param("axle_diameter", 5.0),
    ]

    edits = parse_direct_parameter_edits(
        "zmień średnicę kołowrotka na 150 mm oraz szerokość bieżnika na 50 mm",
        params,
    )

    assert [(edit.name, edit.value) for edit in edits] == [
        ("wheel_diameter", 150.0),
        ("track_width", 50.0),
    ]


def test_relative_percentage_is_computed_from_current_parameter_locally() -> None:
    params = [_param("track_width", 40.0), _param("wheel_diameter", 120.0)]

    edits = parse_direct_parameter_edits("zwiększ szerokość bieżnika o 25%", params)

    assert [(edit.name, edit.value) for edit in edits] == [("track_width", 50.0)]


def test_percentage_without_direction_is_not_guessed() -> None:
    params = [_param("track_width", 40.0)]

    assert parse_direct_parameter_edits("ustaw szerokość bieżnika na 50%", params) == []


def test_relative_millimeter_delta_adds_to_current_value() -> None:
    params = [_param("plate_thickness", 4.0), _param("plate_height", 60.0)]

    edits = parse_direct_parameter_edits("make the plate 2mm thicker", params)

    assert [(edit.name, edit.value) for edit in edits] == [("plate_thickness", 6.0)]


def test_relative_centimeter_delta_can_decrease() -> None:
    params = [_param("track_width", 50.0), _param("wheel_diameter", 150.0)]

    edits = parse_direct_parameter_edits("zmniejsz szerokość bieżnika o 1 cm węższą", params)

    assert [(edit.name, edit.value) for edit in edits] == [("track_width", 40.0)]
