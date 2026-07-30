from pathlib import Path

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2.update_parameter import execute, execute_many
from services.ai.prompts_v2 import SYSTEM_PROMPT, render_turn_context
from services.codegen.models import Build, Design, DesignParameter


def test_update_parameter_rejects_value_above_declared_maximum(tmp_path: Path) -> None:
    design = Design(
        id="wheel",
        revision_id="rev-1",
        name="Hamster wheel",
        script="result = None",
        parameters=[
            DesignParameter(
                name="spoke_count",
                value=6,
                type="count",
                min=3,
                max=12,
            )
        ],
        process="fdm",
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )

    result = execute(
        {
            "name": "spoke_count",
            "new_value": 24,
            "rationale": "Requested 24 rungs, incorrectly mapped to spokes.",
        },
        ctx,
    )

    assert result["code"] == "parameter_above_maximum"
    assert result["maximum"] == 12
    assert design.parameters[0].value == 6


def test_wheel_prompt_distinguishes_rungs_from_spokes() -> None:
    assert "szczebelki" in SYSTEM_PROMPT
    assert "Never map a requested rung count" in SYSTEM_PROMPT


def test_chat_follows_language_of_latest_user_message() -> None:
    assert "language of the user's most recent message" in SYSTEM_PROMPT
    assert "independently of the interface language" in SYSTEM_PROMPT


def test_turn_context_exposes_parameter_range() -> None:
    design = Design(
        id="wheel",
        revision_id="rev-1",
        name="Hamster wheel",
        script="result = None",
        parameters=[
            DesignParameter(name="spoke_count", value=6, type="count", min=3, max=12)
        ],
        process="fdm",
    )

    context = render_turn_context(design, None)

    assert "spoke_count=6 [range 3.0..12.0]" in context


def test_multiple_parameter_updates_build_once(monkeypatch, tmp_path: Path) -> None:
    design = Design(
        id="wheel",
        revision_id="rev-1",
        name="Hamster wheel",
        script="result = None",
        parameters=[
            DesignParameter(name="wheel_diameter", value=120.0, min=80, max=260),
            DesignParameter(name="track_width", value=34.0, min=24, max=70),
        ],
        process="fdm",
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )
    build_calls = 0

    def fake_build(*args, **kwargs):
        nonlocal build_calls
        build_calls += 1
        return Build(revision_id=design.revision_id, mesh_hash="mesh")

    monkeypatch.setattr("services.ai.tools_v2.update_parameter.build_design", fake_build)
    monkeypatch.setattr("services.ai.tools_v2.update_parameter.save_design", lambda *_: None)
    monkeypatch.setattr("services.ai.tools_v2.update_parameter.save_build", lambda *_: None)

    results = execute_many(
        [
            {"name": "wheel_diameter", "new_value": 150, "rationale": "Requested diameter."},
            {"name": "track_width", "new_value": 40, "rationale": "Requested width."},
        ],
        ctx,
    )

    assert build_calls == 1
    assert [parameter.value for parameter in design.parameters] == [150.0, 40.0]
    assert len({result["new_revision_id"] for result in results}) == 1
    assert all(result["ok"] for result in results)
