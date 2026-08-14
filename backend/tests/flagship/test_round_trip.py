"""Phase 0 integration smoke test — survives every refactor in every phase.

For each flagship: build with defaults → mutate the declared test_param →
build again → assert mesh hash differs. If any of these fails, geometry
behavior has regressed and the offending phase doesn't pass its gate.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Heavy deps (cadquery / build123d / trimesh) live behind opt-in flag in CI
# but run by default locally.
pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_FLAGSHIP_TESTS") == "1",
    reason="SKIP_FLAGSHIP_TESTS=1 set; flagship integration tests skipped.",
)


from services.codegen.engine import audit_then_run  # noqa: E402
from services.codegen.flagship import FLAGSHIPS  # noqa: E402


@pytest.mark.parametrize("flagship_id", sorted(FLAGSHIPS.keys()))
def test_flagship_default_build(flagship_id: str) -> None:
    """Each flagship builds cleanly with its default parameters."""
    spec = FLAGSHIPS[flagship_id]
    with tempfile.TemporaryDirectory() as td:
        result = audit_then_run(
            script=spec["script"],
            workspace_dir=Path(td),
            targets=["stl"],
            trusted_source=True,
        )
    assert result.ok, (
        f"Flagship '{flagship_id}' default build failed: "
        f"{result.payload.get('error')}\n"
        f"{(result.payload.get('traceback') or '')[:400]}"
    )
    assert result.payload.get("mesh_hash"), (
        f"Flagship '{flagship_id}' build succeeded but produced no mesh hash."
    )
    bbox = result.payload.get("bbox_mm")
    assert bbox is not None and all(v > 0 for v in bbox), (
        f"Flagship '{flagship_id}' produced an empty / zero-bbox mesh: {bbox}"
    )


@pytest.mark.parametrize("flagship_id", sorted(FLAGSHIPS.keys()))
def test_flagship_param_mutation_changes_mesh(flagship_id: str) -> None:
    """Each flagship's declared test_param actually affects exported geometry.

    This is the *trust* contract: if a parameter is declared and the agent
    mutates it, the user must see geometry change. A 'silent no-op'
    parameter is a bug.
    """
    spec = FLAGSHIPS[flagship_id]
    with tempfile.TemporaryDirectory() as td_a:
        baseline = audit_then_run(
            script=spec["script"],
            workspace_dir=Path(td_a),
            targets=["stl"],
            trusted_source=True,
        )
    assert baseline.ok, f"baseline build for '{flagship_id}' failed"
    baseline_hash = baseline.payload["mesh_hash"]

    with tempfile.TemporaryDirectory() as td_b:
        mutated = audit_then_run(
            script=spec["script"],
            parameter_overrides={spec["test_param"]: spec["test_value"]},
            workspace_dir=Path(td_b),
            targets=["stl"],
            trusted_source=True,
        )
    assert mutated.ok, (
        f"mutated build for '{flagship_id}' failed: "
        f"{mutated.payload.get('error')}"
    )
    mutated_hash = mutated.payload["mesh_hash"]

    assert mutated_hash != baseline_hash, (
        f"Mutating {flagship_id}.{spec['test_param']} to {spec['test_value']} "
        f"did not change the mesh hash. The parameter is a silent no-op — "
        f"the geometry pipeline is not honoring it. This is the worst CAD "
        f"failure mode (chat says edit happened but exported file is unchanged) "
        f"and must be fixed before any other phase work continues."
    )
