from __future__ import annotations

from types import SimpleNamespace

from services import export_bundle


class _Report:
    def model_dump(self) -> dict:
        return {
            "status": "safe",
            "mesh_hash": "canonical-bundle-hash",
            "printer_profile_id": "test-printer",
            "issues": [],
        }


def test_bundle_report_uses_canonical_profile_aware_engine(tmp_path, monkeypatch) -> None:
    stl_path = tmp_path / "model.stl"
    stl_path.write_bytes(b"fixture; canonical engine is mocked")
    captured: dict = {}

    def fake_run_manufacturability(**kwargs):
        captured.update(kwargs)
        return _Report()

    monkeypatch.setattr(
        export_bundle,
        "run_manufacturability",
        fake_run_manufacturability,
    )

    report = export_bundle._canonical_report(
        stl_path,
        SimpleNamespace(id="test-printer"),
    )

    assert captured == {
        "stl_path": stl_path,
        "process": "fdm",
        "printer_profile_id": "test-printer",
    }
    assert report["mesh_hash"] == "canonical-bundle-hash"
