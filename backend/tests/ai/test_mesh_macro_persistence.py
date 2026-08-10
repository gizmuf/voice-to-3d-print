from pathlib import Path

from services.ai.tools_v2 import DesignContext
from services.ai.tools_v2._helpers import append_block_and_build
from services.codegen.models import Build, Design
from services.codegen.sandbox import SandboxResult


def test_mesh_macro_persists_the_preview_without_a_separate_run_build(
    monkeypatch, tmp_path: Path
) -> None:
    design = Design(
        id="imported-part",
        revision_id="rev-1",
        name="Imported part",
        script="mesh = imported_mesh.copy()\nresult = mesh",
        process="fdm",
        metadata={"imported_files": {"imported_mesh": str(tmp_path / "source.stl")}},
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

    monkeypatch.setattr(
        "services.ai.tools_v2._helpers.audit_then_run", lambda **_: sandbox
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
    assert persisted == [(design.id, build)]
    assert ctx.last_build is build

