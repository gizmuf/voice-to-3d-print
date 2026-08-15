from __future__ import annotations

from pathlib import Path

import pytest

import config
from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2.append_feature import execute as append_feature
from services.ai.tools_v2.replace_feature import execute as replace_feature
from services.ai.tools_v2.run_build import execute as run_build
from services.codegen.engine import (
    DesignBuildError,
    audit_then_run,
    design_script_is_trusted,
    trusted_script_metadata,
)
from services.codegen.models import Design, DesignParameter, NamedFeature
from services.codegen.sandbox import SandboxResult
from services.codegen.templates import get_seed_script


BASE_SCRIPT = """from build123d import *
# @feature: body
part = Box(10, 10, 10)
# @end
result = part
"""


def _context(*, trusted: bool) -> DesignContext:
    metadata = trusted_script_metadata(BASE_SCRIPT) if trusted else {}
    design = Design(
        id="feature-edit-trust",
        revision_id="rev-1",
        name="Reviewed template",
        script=BASE_SCRIPT,
        features=[NamedFeature(name="body", source="part = Box(10, 10, 10)")],
        metadata=metadata,
    )
    return DesignContext(
        design_id=design.id,
        design=design,
        output_dir=config.settings.output_dir,
        printer_profile_id="prusa_mk4_default",
    )


@pytest.fixture
def successful_runner(monkeypatch):
    monkeypatch.setattr(
        "services.codegen.engine.run_design",
        lambda **_kwargs: SandboxResult(
            ok=True,
            payload={"parameters": [], "named_features": []},
            stderr="",
            stdout="",
            timed_out=False,
            return_code=0,
        ),
    )
    monkeypatch.setattr("services.ai.tools_v2.replace_feature.save_design", lambda *_: None)
    monkeypatch.setattr("services.ai.tools_v2.append_feature.save_design", lambda *_: None)


@pytest.mark.parametrize("tool", ["replace", "append"])
def test_public_safe_mode_allows_audited_edit_of_exact_trusted_template(
    monkeypatch,
    successful_runner,
    tool: str,
) -> None:
    original_allow_untrusted = config.settings.allow_untrusted_cad_code
    object.__setattr__(config.settings, "allow_untrusted_cad_code", False)
    ctx = _context(trusted=True)
    try:
        if tool == "replace":
            result = replace_feature(
                {
                    "feature_name": "body",
                    "new_code": "part = Box(12, 10, 10)",
                    "rationale": "Make the reviewed body wider.",
                },
                ctx,
            )
        else:
            result = append_feature(
                {
                    "name": "fillet_hint",
                    "code": "shape_hint = 1",
                    "rationale": "Add a harmless reviewed feature.",
                },
                ctx,
            )
    finally:
        object.__setattr__(
            config.settings,
            "allow_untrusted_cad_code",
            original_allow_untrusted,
        )

    assert result["ok"] is True
    assert ctx.design.revision_id != "rev-1"
    assert design_script_is_trusted(ctx.design) is True


@pytest.mark.parametrize("tool", ["replace", "append"])
def test_public_safe_mode_still_rejects_edit_of_untrusted_source(
    monkeypatch,
    tool: str,
) -> None:
    original_allow_untrusted = config.settings.allow_untrusted_cad_code
    object.__setattr__(config.settings, "allow_untrusted_cad_code", False)
    ctx = _context(trusted=False)
    try:
        with pytest.raises(DesignBuildError, match="Untrusted Python"):
            if tool == "replace":
                replace_feature(
                    {
                        "feature_name": "body",
                        "new_code": "part = Box(12, 10, 10)",
                        "rationale": "Attempt an untrusted edit.",
                    },
                    ctx,
                )
            else:
                append_feature(
                    {
                        "name": "untrusted",
                        "code": "shape_hint = 1",
                        "rationale": "Attempt an untrusted append.",
                    },
                    ctx,
                )
    finally:
        object.__setattr__(
            config.settings,
            "allow_untrusted_cad_code",
            original_allow_untrusted,
        )

    assert ctx.design.revision_id == "rev-1"
    assert design_script_is_trusted(ctx.design) is False


@pytest.mark.parametrize("tool", ["replace", "append"])
def test_trusted_source_does_not_bypass_ast_audit(tool: str) -> None:
    original_allow_untrusted = config.settings.allow_untrusted_cad_code
    object.__setattr__(config.settings, "allow_untrusted_cad_code", False)
    ctx = _context(trusted=True)
    try:
        with pytest.raises(DesignBuildError, match="audit"):
            if tool == "replace":
                replace_feature(
                    {
                        "feature_name": "body",
                        "new_code": "import os\npart = Box(12, 10, 10)",
                        "rationale": "Attempt a forbidden import.",
                    },
                    ctx,
                )
            else:
                append_feature(
                    {
                        "name": "forbidden_import",
                        "code": "import os",
                        "rationale": "Attempt a forbidden import.",
                    },
                    ctx,
                )
    finally:
        object.__setattr__(
            config.settings,
            "allow_untrusted_cad_code",
            original_allow_untrusted,
        )

    assert ctx.design.revision_id == "rev-1"
    assert design_script_is_trusted(ctx.design) is True


@pytest.mark.parametrize("tool", ["replace", "append"])
def test_trusted_feature_edit_rejects_allowed_module_file_read_bypass(tool: str) -> None:
    ctx = _context(trusted=True)

    with pytest.raises(DesignBuildError, match="strict CAD allowlist") as caught:
        if tool == "replace":
            replace_feature(
                {
                    "feature_name": "body",
                    "new_code": 'part = Box(12, 10, 10)\nleak = np.fromfile("/proc/1/environ")',
                    "rationale": "Attempt a file read through an allowed module.",
                },
                ctx,
            )
        else:
            append_feature(
                {
                    "name": "file_read",
                    "code": 'leak = np.fromfile("/proc/1/environ")',
                    "rationale": "Attempt a file read through an allowed module.",
                },
                ctx,
            )

    assert any("fromfile" in error for error in caught.value.audit_errors)
    assert ctx.design.revision_id == "rev-1"


def test_legacy_trust_is_not_accepted_for_modified_non_template_script() -> None:
    ctx = _context(trusted=True)
    ctx.design.metadata.pop("trusted_script_policy")

    assert design_script_is_trusted(ctx.design) is False


def test_legacy_exact_builtin_template_can_migrate_to_current_policy() -> None:
    _, script = get_seed_script("simple_box")
    legacy_metadata = trusted_script_metadata(script)
    legacy_metadata.pop("trusted_script_policy")
    legacy_metadata["template_id"] = "simple_box"
    design = Design(
        id="legacy-simple-box",
        revision_id="rev-1",
        name="Legacy simple box",
        script=script,
        metadata=legacy_metadata,
    )

    assert design_script_is_trusted(design) is True


def test_legacy_exact_builtin_template_can_migrate_without_template_id() -> None:
    _, script = get_seed_script("simple_box")
    legacy_metadata = trusted_script_metadata(script)
    legacy_metadata.pop("trusted_script_policy")
    design = Design(
        id="legacy-simple-box-without-template-id",
        revision_id="rev-1",
        name="Legacy simple box",
        script=script,
        metadata=legacy_metadata,
    )

    assert design_script_is_trusted(design) is True


def test_trusted_replace_changes_geometry_and_rebuilds_current_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original_allow_untrusted = config.settings.allow_untrusted_cad_code
    original_output_dir = config.settings.output_dir
    object.__setattr__(config.settings, "allow_untrusted_cad_code", False)
    object.__setattr__(config.settings, "output_dir", tmp_path)
    monkeypatch.setattr("services.ai.tools_v2.replace_feature.save_design", lambda *_: None)
    monkeypatch.setattr("services.ai.tools_v2.run_build.save_build", lambda *_: None)
    _, script = get_seed_script("simple_box")
    legacy_metadata = trusted_script_metadata(script)
    legacy_metadata.pop("trusted_script_policy")
    design = Design(
        id="olga-cage-leg",
        revision_id="rev-1",
        name="60 mm cage leg",
        script=script,
        parameters=[
            DesignParameter(name="width", value=60.0),
            DesignParameter(name="depth", value=60.0),
            DesignParameter(name="height", value=60.0),
            DesignParameter(name="wall_thickness", value=3.0),
            DesignParameter(name="fillet_radius", value=3.0),
            DesignParameter(name="open_top", value=True, type="boolean"),
        ],
        features=[NamedFeature(name="hollow", source="")],
        process="fdm",
        # Matches Olga's pre-migration Firestore document: an exact reviewed
        # seed hash, but no policy marker and no template_id.
        metadata=legacy_metadata,
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
        current_user_message=(
            "Zrób nogę 60 x 60 x 60 mm z wpustem 40 x 40 mm, głębokość 20 mm."
        ),
    )
    try:
        initial = audit_then_run(
            script=ctx.design.script,
            parameter_overrides={p.name: p.value for p in ctx.design.parameters},
            targets=["stl", "glb"],
            trusted_source=True,
        )
        assert initial.ok is True

        edit = replace_feature(
            {
                "feature_name": "hollow",
                "new_code": (
                    "with BuildPart() as recessed:\n"
                    "    add(part.part)\n"
                    "    with Locations((0, 0, height - 20.0)):\n"
                    "        Box(40.0, 40.0, 21.0, mode=Mode.SUBTRACT, "
                    "align=(Align.CENTER, Align.CENTER, Align.MIN))\n"
                    "part = recessed"
                ),
                "rationale": "Add Olga's 40 mm square recess, 20 mm deep.",
            },
            ctx,
        )
        preview = run_build(
            {"targets": ["stl", "glb"], "process": "fdm"},
            ctx,
        )
    finally:
        object.__setattr__(config.settings, "output_dir", original_output_dir)
        object.__setattr__(
            config.settings,
            "allow_untrusted_cad_code",
            original_allow_untrusted,
        )

    assert edit["ok"] is True
    assert preview["ok"] is True
    assert preview["mesh_hash"] != initial.payload["mesh_hash"]
    assert preview["bounding_box_mm"] == pytest.approx((60.0, 60.0, 60.0), abs=0.1)
    assert "glb" in preview["artifacts"]
    assert ctx.last_build is not None
    assert Path(ctx.last_build.artifacts["glb"].path).is_file()
