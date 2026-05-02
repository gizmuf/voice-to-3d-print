"""Every mutable parameter must change the mesh hash after rebuild.

This is the load-bearing trust contract: if the matrix says a parameter is
mutable, then mutating it must produce a different STL. Otherwise the chat
agent could appear to make changes that silently no-op at export time.

This test is slow because it actually builds STLs. It is opt-in via the
``RUN_MESH_HASH_CONTRACTS=1`` env var, since it requires CadQuery to be
installed in the test environment.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MESH_HASH_CONTRACTS") != "1",
    reason="Mesh-hash contracts require CadQuery; opt in with RUN_MESH_HASH_CONTRACTS=1.",
)


def test_perforated_disc_mutable_params_change_mesh(tmp_path):
    import importlib

    os.environ.setdefault("OUTPUT_DIR", str(tmp_path))
    import config

    importlib.reload(config)
    from services.ai.capabilities import _NATIVE_MUTABLE
    from services.editable_rebuild import export_editable_preview
    from services.manufacturability import _hash_mesh
    from services.native_converter import structured_spec_to_editable
    from services.useful_objects import DEFAULT_SPECS

    import trimesh

    spec = {**DEFAULT_SPECS["perforated_disc"], "template_id": "perforated_disc"}
    declared = _NATIVE_MUTABLE["perforated_disc"]

    base_model = structured_spec_to_editable(spec)
    base_glb, base_stl, _ = export_editable_preview(base_model, tmp_path / "base")
    base_hash = _hash_mesh(trimesh.load_mesh(base_stl, force="mesh"))

    bumped: list[tuple[str, str, str]] = []
    for kind, params in declared.items():
        for param in params:
            if not _is_numeric_param(param):
                continue
            tweaked_spec = _bump(spec, kind, param)
            if tweaked_spec is None:
                continue
            tweaked_model = structured_spec_to_editable(tweaked_spec)
            out_dir = tmp_path / f"{kind}_{param}"
            _, tweaked_stl, _ = export_editable_preview(tweaked_model, out_dir)
            tweaked_hash = _hash_mesh(
                trimesh.load_mesh(tweaked_stl, force="mesh")
            )
            assert tweaked_hash != base_hash, (
                f"Mutating {kind}.{param} did not change the mesh hash — "
                f"the rebuild path is not honoring the parameter, which means "
                f"the agent could mutate it and silently produce identical STLs."
            )
            bumped.append((kind, param, tweaked_hash))
    assert bumped, "Expected at least one numeric mutable parameter."


def _is_numeric_param(param: str) -> bool:
    return any(
        param.endswith(suffix)
        for suffix in (
            "_mm",
            "_diameter",
            "_count",
            "_deg",
            "diameter",
            "count",
            "thickness",
        )
    )


def _bump(spec: dict, kind: str, param: str) -> dict | None:
    """Return a deep-copied spec with one parameter mutated by a meaningful amount."""
    import copy

    s = copy.deepcopy(spec)
    target_dict, current = _resolve_param_target(s, kind, param)
    if target_dict is None or current is None:
        return None
    if isinstance(current, (int, float)):
        if param.endswith("_count") or param == "ring_count":
            target_dict[param] = max(1, int(current) + 2)
        else:
            target_dict[param] = float(current) + 1.5
    elif isinstance(current, bool):
        target_dict[param] = not current
    else:
        return None
    return s


def _resolve_param_target(
    spec: dict, kind: str, param: str
) -> tuple[dict | None, object | None]:
    if kind == "body":
        dims = spec.get("dimensions_mm") or {}
        if param in dims:
            return dims, dims[param]
        return None, None
    constraints = spec.get("constraints") or {}
    if param in constraints:
        return constraints, constraints[param]
    return None, None
