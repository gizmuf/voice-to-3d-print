from services.ai.direct_route import ambiguity_question, parse_direct_parameter_edit
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


def test_ambiguous_strength_request_requires_question() -> None:
    assert ambiguity_question("zrób ten wspornik bardziej wytrzymały") is not None
    assert ambiguity_question("ustaw grubość na 6 mm") is None
