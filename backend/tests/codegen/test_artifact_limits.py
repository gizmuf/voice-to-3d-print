from __future__ import annotations

from pathlib import Path

import pytest

from services.codegen import sandbox
from services.codegen.runner import host
from services.codegen.sandbox import run_design


BOX_SCRIPT = """
from build123d import *

result = Box(10, 10, 10)
"""


SPHERE_SCRIPT = """
from build123d import *

result = Sphere(20)
"""


def test_runner_applies_file_size_rlimit_when_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not hasattr(host.resource, "RLIMIT_FSIZE"):
        pytest.skip("RLIMIT_FSIZE is not supported on this platform")

    calls: list[tuple[int, tuple[int, int]]] = []
    monkeypatch.setattr(host.resource, "setrlimit", lambda kind, limits: calls.append((kind, limits)))
    monkeypatch.setattr(host.signal, "signal", lambda *_args: None)

    host.apply_rlimits(max_file_bytes=12_345)

    assert (host.resource.RLIMIT_FSIZE, (12_346, 12_346)) in calls


def test_runner_rejects_oversized_single_artifact(tmp_path: Path) -> None:
    previous_artifact = tmp_path / "model.stl"
    previous_artifact.write_bytes(b"known-good-artifact")
    result = run_design(
        script=SPHERE_SCRIPT,
        targets=["stl"],
        workspace_dir=tmp_path,
        artifact_file_limit_bytes=4 * 1024,
        artifact_total_limit_bytes=64 * 1024,
    )

    assert result.ok is False
    assert result.payload.get("code") == "artifact_size_limit_exceeded"
    assert previous_artifact.read_bytes() == b"known-good-artifact"
    assert not list(tmp_path.glob(".artifact-*"))


def test_runner_rejects_aggregate_artifact_overflow(tmp_path: Path) -> None:
    result = run_design(
        script=BOX_SCRIPT,
        targets=["stl", "step"],
        workspace_dir=tmp_path,
        artifact_file_limit_bytes=1024 * 1024,
        artifact_total_limit_bytes=4 * 1024,
    )

    assert result.ok is False
    assert result.payload.get("code") == "artifact_size_limit_exceeded"
    assert not (tmp_path / "model.stl").exists()
    assert not (tmp_path / "model.step").exists()
    assert not list(tmp_path.glob(".artifact-*"))


def test_runner_allows_normal_artifacts_within_limits(tmp_path: Path) -> None:
    result = run_design(
        script=BOX_SCRIPT,
        targets=["stl", "step", "glb"],
        workspace_dir=tmp_path,
        artifact_file_limit_bytes=8 * 1024 * 1024,
        artifact_total_limit_bytes=16 * 1024 * 1024,
    )

    assert result.ok, result.payload
    artifacts = result.payload["artifacts"]
    assert {"stl", "step", "glb"}.issubset(artifacts)
    artifact_sizes = [Path(path).stat().st_size for path in artifacts.values()]
    assert max(artifact_sizes) <= 8 * 1024 * 1024
    assert sum(artifact_sizes) <= 16 * 1024 * 1024


def test_failed_runner_does_not_reuse_stale_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "result.json").write_text('{"ok": true, "artifacts": {}}')
    monkeypatch.setattr(
        sandbox,
        "_run_bounded",
        lambda *_args, **_kwargs: (-9, "", "", False, False),
    )

    result = sandbox.run_design(
        script=BOX_SCRIPT,
        targets=["stl"],
        workspace_dir=tmp_path,
    )

    assert result.ok is False
    assert "did not produce result.json" in result.payload["error"]
