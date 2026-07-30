from pathlib import Path

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2.update_parameter import execute
from services.ai.prompts_v2 import SYSTEM_PROMPT, render_turn_context
from services.codegen.models import Design, DesignParameter


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
