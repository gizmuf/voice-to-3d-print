from __future__ import annotations

from types import SimpleNamespace

from services.ai.tools import run_preview as tool


class _Report:
    mesh_hash = "canonical-preview-hash"
    status = "safe"
    issues: list = []

    def model_dump(self) -> dict:
        return {
            "status": self.status,
            "issues": self.issues,
            "mesh_hash": self.mesh_hash,
            "printer_profile_id": "test-printer",
        }


class _Context(SimpleNamespace):
    def workspace_artifact_url(self, path) -> str:
        return f"/artifacts/workspaces/{self.workspace_id}/{path.name}"


def test_preview_uses_canonical_profile_aware_report(tmp_path, monkeypatch) -> None:
    glb_path = tmp_path / "preview.glb"
    stl_path = tmp_path / "preview.stl"
    glb_path.write_bytes(b"glb")
    stl_path.write_bytes(b"stl")

    captured: dict = {}
    recorded: dict = {}

    monkeypatch.setattr(
        tool,
        "export_editable_preview",
        lambda model, workspace_dir: (
            glb_path,
            stl_path,
            {"geometry_valid": True},
        ),
    )

    def fake_run_manufacturability(**kwargs):
        captured.update(kwargs)
        return _Report()

    monkeypatch.setattr(tool, "run_manufacturability", fake_run_manufacturability)
    monkeypatch.setattr(
        tool,
        "record_preview",
        lambda workspace_id, **kwargs: recorded.update(
            {"workspace_id": workspace_id, **kwargs}
        ),
    )

    ctx = _Context(
        output_dir=tmp_path,
        workspace_id="workspace-1",
        model=SimpleNamespace(revision_id="revision-1"),
        printer_profile=SimpleNamespace(id="test-printer"),
        last_preview=None,
    )

    result = tool.execute({}, ctx)

    assert captured == {
        "stl_path": stl_path,
        "process": "fdm",
        "printer_profile_id": "test-printer",
    }
    assert result["mesh_hash"] == "canonical-preview-hash"
    assert result["manufacturability"] == {
        "status": "safe",
        "issue_count": 0,
        "summary": [],
    }
    assert recorded["validation"]["mesh_hash"] == "canonical-preview-hash"
    assert recorded["validation"]["manufacturability"]["printer_profile_id"] == (
        "test-printer"
    )
    assert ctx.last_preview["mesh_hash"] == "canonical-preview-hash"
