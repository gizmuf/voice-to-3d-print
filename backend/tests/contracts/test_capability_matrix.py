"""Contract tests for the AI capability matrix.

These guarantee that ``services.ai.capabilities`` cannot drift away from the
shapes the rest of the pipeline actually produces:

- Every native template the matrix declares as mutable must round-trip
  through ``structured_spec_to_editable``: the declared (kind, param) pairs
  must exist on the seeded tree.
- The STL reconstruction matrix must mirror the actual reconstruction
  output: any param the matrix says is mutable must show up on the
  reconstructed tree, and any kind the reconstruction emits must be
  represented in the matrix (or explicitly refused).

If reconstruction starts emitting a new editable shape, these tests fail
loudly — forcing capabilities.py to be updated alongside the new behavior.
"""

from __future__ import annotations

import pytest

from services.ai.capabilities import (
    _NATIVE_MUTABLE,
    _STL_RECONSTRUCTED_MUTABLE,
    capability_for,
)
from services.editable_model import BodyNode, EditableModel
from services.native_converter import structured_spec_to_editable
from services.stl_reconstruction import reconstruct_from_analysis
from services.useful_objects import DEFAULT_SPECS


def _walk(bodies):
    for body in bodies:
        yield body
        yield from _walk(body.children)


def _by_kind(bodies) -> dict[str, list[BodyNode]]:
    out: dict[str, list[BodyNode]] = {}
    for body in _walk(bodies):
        out.setdefault(body.kind, []).append(body)
    return out


@pytest.mark.parametrize("template_id", sorted(_NATIVE_MUTABLE.keys()))
def test_native_capability_aligns_with_seeded_tree(template_id: str) -> None:
    spec = DEFAULT_SPECS.get(template_id)
    assert spec, f"DEFAULT_SPECS missing entry for {template_id!r}"
    spec = {**spec, "template_id": template_id}
    model = structured_spec_to_editable(spec)
    by_kind = _by_kind(model.bodies)

    declared = _NATIVE_MUTABLE[template_id]
    for kind, params in declared.items():
        assert kind in by_kind, (
            f"Capability matrix declares mutable params on kind '{kind}' for "
            f"template '{template_id}', but no node of that kind appears in the "
            f"seeded tree. Seeded kinds: {sorted(by_kind.keys())}"
        )
        seen = set()
        for body in by_kind[kind]:
            seen.update(k for k in body.params if not k.startswith("_"))
        for param in params:
            assert param in seen, (
                f"Capability matrix declares '{param}' mutable on kind '{kind}' "
                f"for template '{template_id}', but no node of that kind exposes "
                f"it. Available params on those nodes: {sorted(seen)}"
            )


def test_stl_reconstruction_emits_declared_shape() -> None:
    """The reconstruction emits exactly the shape the matrix claims."""
    analysis = {
        "extents_mm": [340.0, 340.0, 6.0],
        "warnings": [],
        "targets": [
            {
                "id": "stl:root:pattern",
                "type": "planar_pattern_face",
                "topology": "radial",
                "feature_kind": "circular_hole",
                "label": "Hole pattern",
                "editable": True,
                "confidence": 0.92,
                "fit": {"center_hole_feature_id": "f0"},
                "measured": {
                    "feature_size": 7.0,
                    "ring_count": 12,
                    "radial_spacing": 18.0,
                    "spacing_x": 14.0,
                    "margin": 6.0,
                    "center_hole_diameter": 16.0,
                },
                "warnings": [],
            },
            {
                "id": "stl:root:center_hole",
                "type": "single_planar_feature",
                "feature_id": "f0",
                "feature_kind": "circular_hole",
                "label": "Center hole",
                "editable": True,
                "confidence": 0.95,
                "measured": {"diameter": 16.0},
                "warnings": [],
            },
        ],
    }
    model, mode = reconstruct_from_analysis(analysis)
    assert model is not None, f"Reconstruction failed: mode={mode}"
    assert model.source == "stl_reconstructed"
    by_kind = _by_kind(model.bodies)

    declared = _STL_RECONSTRUCTED_MUTABLE.get("perforated_disc", {})
    assert declared, "STL reconstructed matrix should declare perforated_disc."

    for kind, params in declared.items():
        assert kind in by_kind, (
            f"Matrix declares stl_reconstructed kind '{kind}' but reconstruction "
            f"did not emit it. Emitted kinds: {sorted(by_kind.keys())}"
        )
        seen = set()
        for body in by_kind[kind]:
            seen.update(k for k in body.params if not k.startswith("_"))
        for param in params:
            assert param in seen, (
                f"Matrix declares stl_reconstructed param '{param}' on kind "
                f"'{kind}' but no reconstructed node exposes it. "
                f"Available: {sorted(seen)}"
            )

    # Reverse direction: any kind reconstruction emits with editable params
    # must be representable in the matrix or the test should be updated.
    for kind, nodes in by_kind.items():
        # ``body`` and ``thickness`` and ``hole`` and ``circular_pattern`` should be present.
        if kind not in declared:
            # Allow only kinds without editable params on the emitted nodes.
            for body in nodes:
                public = [k for k in body.params if not k.startswith("_")]
                assert not public or not body.editable, (
                    f"Reconstruction emits editable kind '{kind}' with params "
                    f"{public}, but the matrix does not declare it. Update "
                    f"capabilities.py or add a refusal."
                )


def test_step_import_capability_refuses_all() -> None:
    model = EditableModel(
        id="x",
        source="step_import",
        revision_id="r0",
        bodies=[
            BodyNode(
                id="step:root",
                kind="body",
                label="ref.step",
                editable=False,
                confidence=0.0,
                params={"_template_id": "step_reference", "width_mm": 100.0},
                children=[],
            )
        ],
    )
    capability = capability_for(model)
    assert capability.unsupported_reasons.get("mutate_parameter")
    assert capability.unsupported_reasons.get("add_feature")
    assert capability.unsupported_reasons.get("remove_feature")
    assert not capability.mutable_params_by_node_kind
