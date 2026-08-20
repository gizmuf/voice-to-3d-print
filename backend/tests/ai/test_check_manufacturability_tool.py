from __future__ import annotations

from types import SimpleNamespace

from services.ai.tools import check_manufacturability as tool


class _Report:
    mesh_hash = "canonical-mesh-hash"

    def model_dump(self) -> dict:
        return {
            "status": "safe",
            "printer_profile_id": "test-printer",
            "issues": [],
        }


def test_tool_delegates_to_profile_aware_canonical_engine(tmp_path, monkeypatch) -> None:
    stl_path = tmp_path / "preview.stl"
    stl_path.write_bytes(b"preview fixture; canonical engine is mocked")

    captured: dict = {}

    def fake_run_manufacturability(**kwargs):
        captured.update(kwargs)
        return _Report()

    monkeypatch.setattr(tool, "run_manufacturability", fake_run_manufacturability)

    ctx = SimpleNamespace(
        output_dir=tmp_path,
        workspace_id="workspace-1",
        model=SimpleNamespace(revision_id="revision-1"),
        printer_profile=SimpleNamespace(id="test-printer"),
        last_preview={
            "revision_id": "revision-1",
            "stl_path": str(stl_path),
        },
    )

    result = tool.execute({}, ctx)

    assert captured == {
        "stl_path": stl_path,
        "process": "fdm",
        "printer_profile_id": "test-printer",
    }
    assert result == {
        "ok": True,
        "revision_id": "revision-1",
        "mesh_hash": "canonical-mesh-hash",
        "report": {
            "status": "safe",
            "printer_profile_id": "test-printer",
            "issues": [],
        },
    }
