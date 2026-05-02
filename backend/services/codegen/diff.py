"""Revision diff helpers for code-driven designs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import settings
from services.codegen.models import Build, Design


def revision_diff(design_id: str, revision_id: str) -> dict[str, Any]:
    rev_dir = _revision_dir(design_id, revision_id)
    design = _load_design(rev_dir)
    build = _load_build(rev_dir)
    if design is None and build is None:
        raise FileNotFoundError(f"Revision {revision_id} not found for design {design_id}")

    parent_id = design.parent_revision_id if design else None
    parent_dir = _revision_dir(design_id, parent_id) if parent_id else None
    parent_design = _load_design(parent_dir) if parent_dir else None
    parent_build = _load_build(parent_dir) if parent_dir else None

    current_params = build.parameter_snapshot if build else _param_snapshot(design)
    parent_params = parent_build.parameter_snapshot if parent_build else _param_snapshot(parent_design)
    parameter_changes = []
    for name in sorted(set(parent_params) | set(current_params)):
        before = parent_params.get(name)
        after = current_params.get(name)
        if before != after:
            parameter_changes.append({"name": name, "before": before, "after": after})

    current_features = {f.id: f for f in (design.features if design else [])}
    parent_features = {f.id: f for f in (parent_design.features if parent_design else [])}
    added = [
        {"id": fid, "name": f.name, "kind": f.kind}
        for fid, f in current_features.items()
        if fid not in parent_features
    ]
    removed = [
        {"id": fid, "name": f.name, "kind": f.kind}
        for fid, f in parent_features.items()
        if fid not in current_features
    ]

    return {
        "design_id": design_id,
        "revision_id": revision_id,
        "parent_revision_id": parent_id,
        "parameter_changes": parameter_changes,
        "features_added": added,
        "features_removed": removed,
        "duration_ms": build.duration_ms if build else None,
        "mesh_hash": build.mesh_hash if build else None,
        "bounding_box_mm": build.bounding_box_mm if build else None,
        "print_estimate": build.print_estimate.model_dump(mode="json") if build and build.print_estimate else None,
    }


def _revision_dir(design_id: str, revision_id: str | None) -> Path:
    return settings.output_dir / "designs" / design_id / "revisions" / (revision_id or "")


def _load_design(rev_dir: Path | None) -> Design | None:
    if rev_dir is None:
        return None
    path = rev_dir / "design.json"
    if not path.exists():
        return None
    try:
        return Design.model_validate_json(path.read_text())
    except Exception:
        return None


def _load_build(rev_dir: Path | None) -> Build | None:
    if rev_dir is None:
        return None
    path = rev_dir / "build.json"
    if not path.exists():
        return None
    try:
        return Build.model_validate_json(path.read_text())
    except Exception:
        return None


def _param_snapshot(design: Design | None) -> dict[str, Any]:
    if design is None:
        return {}
    return {p.name: p.value for p in design.parameters}


__all__ = ["revision_diff"]
