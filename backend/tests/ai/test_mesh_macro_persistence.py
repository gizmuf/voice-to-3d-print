from pathlib import Path

import pytest

from config import settings
from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build
from services.ai.tools_v2.mesh_modify_holes import execute as execute_mesh_modify_holes
from services.codegen.engine import (
    DesignBuildError,
    design_script_is_trusted,
    trusted_script_metadata,
)
from services.codegen.models import Build, Design
from services.codegen.sandbox import SandboxResult


def test_mesh_macro_persists_the_preview_without_a_separate_run_build(
    monkeypatch, tmp_path: Path
) -> None:
    script = "mesh = imported_mesh.copy()\nresult = mesh"
    design = Design(
        id="imported-part",
        revision_id="rev-1",
        name="Imported part",
        script=script,
        process="fdm",
        metadata={
            "imported_files": {"imported_mesh": str(tmp_path / "source.stl")},
            **trusted_script_metadata(script),
        },
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )
    sandbox = SandboxResult(
        ok=True,
        payload={"mesh_hash": "changed-mesh", "named_features": []},
        stderr="",
        stdout="",
        timed_out=False,
        return_code=0,
    )
    build = Build(revision_id="rev-2", mesh_hash="changed-mesh")
    persisted: list[tuple[str, Build]] = []
    audit_calls: list[dict] = []

    def trusted_audit(**kwargs):
        audit_calls.append(kwargs)
        return sandbox

    monkeypatch.setattr(
        "services.ai.tools_v2._helpers.audit_then_run", trusted_audit
    )
    monkeypatch.setattr(
        "services.ai.tools_v2._helpers.build_from_sandbox_result",
        lambda *_args, **_kwargs: build,
    )
    monkeypatch.setattr("services.ai.tools_v2._helpers.save_design", lambda *_: None)
    monkeypatch.setattr(
        "services.ai.tools_v2._helpers.save_build",
        lambda design_id, saved_build: persisted.append((design_id, saved_build)),
    )

    result = append_block_and_build(
        ctx,
        feature_name="inflate_surface",
        block="mesh.vertices += mesh.vertex_normals * 0.2",
    )

    assert result["mesh_hash"] == "changed-mesh"
    assert audit_calls[0]["trusted_source"] is True
    assert design_script_is_trusted(design) is True
    assert persisted == [(design.id, build)]
    assert ctx.last_build is build


@pytest.mark.parametrize("macro_path", ["shared", "holes"])
@pytest.mark.parametrize(
    "source_metadata",
    [
        {},
        {"trusted_script": True},
        trusted_script_metadata("different script bytes"),
    ],
    ids=["missing-provenance", "legacy-marker", "mismatched-digest"],
)
def test_mesh_macros_reject_untrusted_source_without_laundering_digest(
    monkeypatch,
    tmp_path: Path,
    macro_path: str,
    source_metadata: dict,
) -> None:
    original_script = "mesh = imported_mesh.copy()\nresult = mesh"
    design = Design(
        id=f"untrusted-{macro_path}",
        revision_id="rev-1",
        name="Imported part",
        script=original_script,
        process="fdm",
        metadata={
            "imported_files": {"imported_mesh": str(tmp_path / "source.stl")},
            **source_metadata,
        },
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )
    original_public_safe_mode = settings.public_safe_mode
    original_allow_untrusted = settings.allow_untrusted_cad_code
    object.__setattr__(settings, "public_safe_mode", True)
    object.__setattr__(settings, "allow_untrusted_cad_code", False)
    monkeypatch.setattr(
        "services.codegen.engine.run_design",
        lambda **_kwargs: pytest.fail("untrusted macro reached the sandbox runner"),
    )
    try:
        with pytest.raises(DesignBuildError, match="Untrusted Python"):
            if macro_path == "shared":
                append_block_and_build(
                    ctx,
                    feature_name="inflate_surface",
                    block="mesh.vertices += mesh.vertex_normals * 0.2",
                )
            else:
                execute_mesh_modify_holes(
                    {
                        "delta_mm": -0.5,
                        "rationale": "Tighten every imported mesh hole.",
                    },
                    ctx,
                )
    finally:
        object.__setattr__(
            settings, "public_safe_mode", original_public_safe_mode
        )
        object.__setattr__(
            settings, "allow_untrusted_cad_code", original_allow_untrusted
        )

    assert design.script == original_script
    assert design.revision_id == "rev-1"
    assert design_script_is_trusted(design) is False


def test_mesh_modify_holes_preserves_exact_trusted_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    script = "mesh = imported_mesh.copy()\nresult = mesh"
    design = Design(
        id="trusted-hole-modification",
        revision_id="rev-1",
        name="Imported part",
        script=script,
        process="fdm",
        metadata={
            "imported_files": {"imported_mesh": str(tmp_path / "source.stl")},
            **trusted_script_metadata(script),
        },
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )
    sandbox = SandboxResult(
        ok=True,
        payload={"mesh_hash": "holes-changed", "named_features": []},
        stderr="",
        stdout="",
        timed_out=False,
        return_code=0,
    )
    build = Build(revision_id="rev-2", mesh_hash="holes-changed")
    audit_calls: list[dict] = []

    def trusted_audit(**kwargs):
        audit_calls.append(kwargs)
        return sandbox

    monkeypatch.setattr(
        "services.ai.tools_v2.mesh_modify_holes.audit_then_run", trusted_audit
    )
    monkeypatch.setattr(
        "services.ai.tools_v2.mesh_modify_holes.build_from_sandbox_result",
        lambda *_args, **_kwargs: build,
    )
    monkeypatch.setattr(
        "services.ai.tools_v2.mesh_modify_holes.save_design", lambda *_: None
    )
    monkeypatch.setattr(
        "services.ai.tools_v2.mesh_modify_holes.save_build", lambda *_: None
    )

    result = execute_mesh_modify_holes(
        {
            "delta_mm": -0.5,
            "rationale": "Tighten every imported mesh hole.",
        },
        ctx,
    )

    assert result["mesh_hash"] == "holes-changed"
    assert audit_calls[0]["trusted_source"] is True
    assert design_script_is_trusted(design) is True
    assert ctx.last_build is build


@pytest.mark.parametrize("macro_path", ["shared", "holes"])
def test_permissive_untrusted_macro_never_mints_trusted_digest(
    monkeypatch, tmp_path: Path, macro_path: str
) -> None:
    script = "mesh = imported_mesh.copy()\nresult = mesh"
    design = Design(
        id=f"permissive-untrusted-{macro_path}",
        revision_id="rev-1",
        name="Imported part",
        script=script,
        process="fdm",
        metadata={
            "imported_files": {"imported_mesh": str(tmp_path / "source.stl")},
            "trusted_script": True,
        },
    )
    ctx = DesignContext(
        design_id=design.id,
        design=design,
        output_dir=tmp_path,
        printer_profile_id="prusa_mk4_default",
    )
    sandbox = SandboxResult(
        ok=True,
        payload={"mesh_hash": "untrusted-change", "named_features": []},
        stderr="",
        stdout="",
        timed_out=False,
        return_code=0,
    )
    build = Build(revision_id="rev-2", mesh_hash="untrusted-change")
    audit_calls: list[dict] = []

    def permissive_audit(**kwargs):
        audit_calls.append(kwargs)
        return sandbox

    module = (
        "services.ai.tools_v2._helpers"
        if macro_path == "shared"
        else "services.ai.tools_v2.mesh_modify_holes"
    )
    monkeypatch.setattr(f"{module}.audit_then_run", permissive_audit)
    monkeypatch.setattr(
        f"{module}.build_from_sandbox_result", lambda *_args, **_kwargs: build
    )
    monkeypatch.setattr(f"{module}.save_design", lambda *_: None)
    monkeypatch.setattr(f"{module}.save_build", lambda *_: None)

    if macro_path == "shared":
        result = append_block_and_build(
            ctx,
            feature_name="inflate_surface",
            block="mesh.vertices += mesh.vertex_normals * 0.2",
        )
    else:
        result = execute_mesh_modify_holes(
            {
                "delta_mm": -0.5,
                "rationale": "Tighten every imported mesh hole.",
            },
            ctx,
        )

    assert result["mesh_hash"] == "untrusted-change"
    assert audit_calls[0]["trusted_source"] is False
    assert "trusted_script" not in design.metadata
    assert "trusted_script_sha256" not in design.metadata
    assert design_script_is_trusted(design) is False
