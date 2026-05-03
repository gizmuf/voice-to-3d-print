"""Disk-backed persistence for Designs, builds, and conversations.

One directory per design at ``output_dir/designs/{design_id}``:
- ``design.json``        — the Design record (script + parameters + features + metadata)
- ``build.json``         — the most recent Build record (artifacts + manufacturability)
- ``conversation.json``  — chat history for the AI agent
- ``model.{stl,step,glb,dxf,gcode}`` — artifacts written by the sandbox / slicer
- ``revisions/{rev_id}/`` — per-revision snapshot (script + build) for branching
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import settings
from services.codegen.models import Build, Design, DesignRecord


def _root() -> Path:
    p = settings.output_dir / "designs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _design_dir(design_id: str) -> Path:
    p = _root() / design_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _design_path(design_id: str) -> Path:
    return _design_dir(design_id) / "design.json"


def _build_path(design_id: str) -> Path:
    return _design_dir(design_id) / "build.json"


def _feature_graph_path(design_id: str) -> Path:
    return _design_dir(design_id) / "feature_graph.json"


def _conversation_path(design_id: str) -> Path:
    return _design_dir(design_id) / "conversation.json"


def new_design_id() -> str:
    return uuid.uuid4().hex


def new_revision_id() -> str:
    return uuid.uuid4().hex


def create_design(
    *,
    name: str,
    script: str,
    parameters: list | None = None,
    features: list | None = None,
    process: str = "either",
    metadata: dict | None = None,
    design_id: str | None = None,
) -> Design:
    design_id = design_id or new_design_id()
    design = Design(
        id=design_id,
        revision_id=new_revision_id(),
        name=name,
        script=script,
        parameters=parameters or [],
        features=features or [],
        process=process,  # type: ignore[arg-type]
        metadata=metadata or {},
    )
    save_design(design)
    return design


def save_design(design: Design) -> Design:
    for feature in design.features:
        if not feature.revision_id:
            feature.revision_id = design.revision_id
    path = _design_path(design.id)
    path.write_text(json.dumps(design.model_dump(mode="json"), indent=2))
    _feature_graph_path(design.id).write_text(
        json.dumps(
            {
                "design_id": design.id,
                "revision_id": design.revision_id,
                "features": [f.model_dump(mode="json") for f in design.features],
            },
            indent=2,
        )
    )
    return design


def get_design(design_id: str) -> Design:
    path = _design_path(design_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Design {design_id} not found.")
    return Design.model_validate_json(path.read_text())


def get_design_or_none(design_id: str) -> Design | None:
    path = _design_path(design_id)
    if not path.exists():
        return None
    try:
        return Design.model_validate_json(path.read_text())
    except Exception:
        return None


def save_build(design_id: str, build: Build) -> Build:
    path = _build_path(design_id)
    path.write_text(json.dumps(build.model_dump(mode="json"), indent=2))
    revision_dir = _design_dir(design_id) / "revisions" / build.revision_id
    revision_dir.mkdir(parents=True, exist_ok=True)
    (revision_dir / "build.json").write_text(json.dumps(build.model_dump(mode="json"), indent=2))
    # Snapshot the design (script + parameters) alongside the build so a
    # later restore_revision can fully rewind, not just promote artifacts.
    design = get_design_or_none(design_id)
    if design is not None:
        (revision_dir / "design.json").write_text(
            json.dumps(design.model_dump(mode="json"), indent=2)
        )
        (revision_dir / "feature_graph.json").write_text(
            json.dumps(
                {
                    "design_id": design.id,
                    "revision_id": design.revision_id,
                    "features": [f.model_dump(mode="json") for f in design.features],
                },
                indent=2,
            )
        )
    _sync_to_legacy_workspace(design_id, build)
    prune_revisions(design_id, keep_last=settings.revision_keep_last)
    return build


def prune_revisions(
    design_id: str,
    *,
    keep_last: int,
    extra_pinned: set[str] | None = None,
) -> int:
    """Drop old revision artifact dirs to bound disk usage.

    Always retains: the current head (so the design can re-render) and any
    ``extra_pinned`` IDs the caller provides. Beyond that we keep the
    ``keep_last`` most-recent revisions by mtime. We intentionally do not keep
    the full parent chain: normal revision history is linear, so recursive
    parent retention would keep every old revision forever.
    """
    if keep_last <= 0:
        return 0
    revisions_dir = _design_dir(design_id) / "revisions"
    if not revisions_dir.exists():
        return 0
    pinned: set[str] = set(extra_pinned or set())
    design = get_design_or_none(design_id)
    if design is not None:
        pinned.add(design.revision_id)

    entries: list[tuple[str, Path, float]] = []
    for child in revisions_dir.iterdir():
        if not child.is_dir():
            continue
        bjson = child / "build.json"
        if not bjson.exists():
            continue
        entries.append((child.name, child, bjson.stat().st_mtime))
    entries.sort(key=lambda e: e[2], reverse=True)

    keep: set[str] = set(pinned)
    for rev_id, _, _ in entries[:keep_last]:
        keep.add(rev_id)

    import shutil

    deleted = 0
    for rev_id, child, _ in entries:
        if rev_id in keep:
            continue
        shutil.rmtree(child, ignore_errors=True)
        deleted += 1
    return deleted


def _sync_to_legacy_workspace(design_id: str, build: Build) -> None:
    """If a legacy Workspace exists at the same id, mirror the new build's
    GLB / STL into its ``latest_preview`` so the old `/?workspace=…` UI shows
    the geometry produced by the powerful agent.

    Best-effort: never raises. The legacy chat path bridges to a Design at
    the same id, but the legacy UI's viewer still reads workspace state.
    Without this sync the viewer would show the old, pre-edit GLB.
    """
    try:
        from services.workspace import _workspace_path, get_workspace, save_workspace  # type: ignore

        ws_path = _workspace_path(design_id)
        if not ws_path.exists():
            return
        record = get_workspace(design_id)
    except Exception:
        return

    glb = build.artifacts.get("glb")
    stl = build.artifacts.get("stl")
    glb_url = glb.url if glb else None
    stl_url = stl.url if stl else None
    if not glb_url and not stl_url:
        return

    from services.editable_model import PreviewArtifact

    record.latest_preview = PreviewArtifact(
        revision_id=build.revision_id,
        glb_url=glb_url or "",
        stl_url=stl_url,
        validation={
            "source": "design_engine",
            "mesh_hash": build.mesh_hash,
            "manufacturability": (
                build.manufacturability.model_dump() if build.manufacturability else None
            ),
        },
    )
    # Keep the workspace's editable_model.revision_id in lockstep so its
    # ensure_current_revision checks still pass after a bridged edit.
    record.editable_model.revision_id = build.revision_id
    try:
        save_workspace(record)
    except Exception:
        return


def get_build(design_id: str) -> Build | None:
    path = _build_path(design_id)
    if not path.exists():
        return None
    try:
        return Build.model_validate_json(path.read_text())
    except Exception:
        return None


def get_record(design_id: str) -> DesignRecord:
    design = get_design(design_id)
    return DesignRecord(design=design, latest_build=get_build(design_id))


def list_designs() -> list[Design]:
    out: list[Design] = []
    if not _root().exists():
        return out
    for child in _root().iterdir():
        if not child.is_dir():
            continue
        try:
            out.append(Design.model_validate_json((child / "design.json").read_text()))
        except Exception:
            continue
    out.sort(key=lambda d: d.metadata.get("updated_at", ""), reverse=True)
    return out


def update_design_script(
    design_id: str,
    *,
    script: str,
    parameters: list,
    features: list,
    parent_revision_id: str | None = None,
) -> Design:
    design = get_design(design_id)
    design.parent_revision_id = parent_revision_id or design.revision_id
    design.revision_id = new_revision_id()
    design.script = script
    design.parameters = parameters
    design.features = features
    return save_design(design)


def load_conversation(design_id: str) -> list[dict]:
    path = _conversation_path(design_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_conversation(design_id: str, messages: list[dict]) -> None:
    path = _conversation_path(design_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2))


def list_revisions(design_id: str) -> list[dict]:
    """Enumerate the persisted revisions for a design, newest first.

    Each revision was saved by ``save_build`` to ``revisions/{rev_id}/build.json``
    so we walk that directory and read each one. Returns a compact summary
    (no full artifact list) suitable for the timeline thumbnails strip.
    """
    revisions_dir = _design_dir(design_id) / "revisions"
    if not revisions_dir.exists():
        return []
    out: list[dict] = []
    for child in revisions_dir.iterdir():
        if not child.is_dir():
            continue
        bjson = child / "build.json"
        if not bjson.exists():
            continue
        try:
            payload = json.loads(bjson.read_text())
        except Exception:
            continue
        artifacts = payload.get("artifacts") or {}
        glb = artifacts.get("glb")
        out.append(
            {
                "revision_id": payload.get("revision_id", child.name),
                "mesh_hash": payload.get("mesh_hash"),
                "bounding_box_mm": payload.get("bounding_box_mm"),
                "manufacturability_status": (
                    (payload.get("manufacturability") or {}).get("status")
                ),
                "duration_ms": payload.get("duration_ms"),
                "glb_url": (glb or {}).get("url") if isinstance(glb, dict) else None,
                "stat_mtime": bjson.stat().st_mtime,
            }
        )
    out.sort(key=lambda r: r["stat_mtime"], reverse=True)
    return out


def delete_revision(design_id: str, revision_id: str) -> bool:
    """Remove a past revision's snapshot directory from disk.

    Refuses to delete the current head (would orphan the design). Returns
    True when something was removed.
    """
    design = get_design_or_none(design_id)
    if design is None:
        raise FileNotFoundError(f"Design {design_id} not found")
    if design.revision_id == revision_id:
        raise ValueError(
            "Cannot delete the current revision. Restore an older revision "
            "first if you really want to discard this one."
        )

    rev_dir = _design_dir(design_id) / "revisions" / revision_id
    if not rev_dir.exists():
        return False

    import shutil

    shutil.rmtree(rev_dir, ignore_errors=True)
    return not rev_dir.exists()


def restore_revision(design_id: str, revision_id: str):
    """Roll the design back to a past revision — script, parameters, build.

    Restores from the snapshot stored at ``revisions/{rev_id}/design.json``
    plus the build at ``revisions/{rev_id}/build.json``. The current revision
    becomes a child of this one (fork-from-here) — the user can edit and the
    new edits branch off from the restored point.
    """
    rev_dir = _design_dir(design_id) / "revisions" / revision_id
    build_path = rev_dir / "build.json"
    design_path = rev_dir / "design.json"

    if not build_path.exists():
        raise FileNotFoundError(
            f"Revision {revision_id} not found for design {design_id}"
        )

    build_payload = json.loads(build_path.read_text())
    _build_path(design_id).write_text(json.dumps(build_payload, indent=2))

    if design_path.exists():
        # Full rewind — the script + parameters as they were at that revision
        snapshot = Design.model_validate_json(design_path.read_text())
        # Mark the *current* head as the parent so the user's next edit
        # creates a new branch off the restored point.
        live = get_design(design_id)
        snapshot.parent_revision_id = live.revision_id
        save_design(snapshot)
    else:
        # Older revision (pre-snapshot era) — promote the build only.
        design = get_design(design_id)
        design.parent_revision_id = design.revision_id
        design.revision_id = revision_id
        save_design(design)

    return build_payload


__all__ = [
    "create_design",
    "save_design",
    "get_design",
    "get_design_or_none",
    "save_build",
    "get_build",
    "get_record",
    "list_designs",
    "list_revisions",
    "restore_revision",
    "delete_revision",
    "prune_revisions",
    "update_design_script",
    "load_conversation",
    "save_conversation",
    "new_design_id",
    "new_revision_id",
]
