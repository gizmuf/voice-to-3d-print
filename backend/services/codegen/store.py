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
import logging
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import settings
from services.codegen import cloud_store
from services.codegen.models import Build, Design, DesignRecord


logger = logging.getLogger(__name__)


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
    design_metadata = dict(metadata or {})
    try:
        from services.auth import current_owner_id

        owner_id = current_owner_id()
        if owner_id and "owner_id" not in design_metadata:
            design_metadata["owner_id"] = owner_id
    except Exception:
        # Auth context is an API boundary concern; offline migrations and
        # isolated build scripts can still create records explicitly.
        pass
    design = Design(
        id=design_id,
        revision_id=new_revision_id(),
        name=name,
        script=script,
        parameters=parameters or [],
        features=features or [],
        process=process,  # type: ignore[arg-type]
        metadata=design_metadata,
    )
    save_design(design)
    return design


def save_design(design: Design) -> Design:
    for feature in design.features:
        if not feature.revision_id:
            feature.revision_id = design.revision_id
    payload = design.model_dump(mode="json")
    path = _design_path(design.id)
    path.write_text(json.dumps(payload, indent=2))
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
    cloud_store.save_design_payload(design.id, payload)
    return design


def _read_local_design(path: Path) -> Design | None:
    try:
        return Design.model_validate_json(path.read_text())
    except Exception as exc:
        logger.warning("Failed to load design from %s: %s", path, exc)
        return None


def _prefer_newer_design(local: Design | None, remote_payload: dict | None) -> Design | None:
    if remote_payload is None:
        return local
    try:
        remote = Design.model_validate(remote_payload)
    except Exception as exc:
        logger.warning("Failed to validate remote design payload: %s", exc)
        return local
    if local is None:
        return remote
    if remote.revision_id != local.revision_id:
        return remote
    return local


def get_design(design_id: str) -> Design:
    path = _design_path(design_id)
    local = _read_local_design(path) if path.exists() else None
    remote_payload = None
    try:
        remote_payload = cloud_store.load_design_payload(design_id)
    except Exception as exc:
        if local is None:
            raise
        logger.warning("Durable design load failed for %s: %s", design_id, exc)
    chosen = _prefer_newer_design(local, remote_payload)
    if chosen is None:
        raise HTTPException(status_code=404, detail=f"Design {design_id} not found.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(chosen.model_dump(mode="json"), indent=2))
    return chosen


def get_design_or_none(design_id: str) -> Design | None:
    try:
        return get_design(design_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    except Exception as exc:
        # Distinguish "file is corrupt" from "design doesn't exist". A bare
        # None return masks the difference and the caller has no signal that
        # something on disk needs attention.
        logger.warning("Failed to load design %s: %s", design_id, exc)
        return None


def save_build(design_id: str, build: Build) -> Build:
    cloud_store.upload_build_artifacts(design_id, build)
    path = _build_path(design_id)
    build_payload = build.model_dump(mode="json")
    path.write_text(json.dumps(build_payload, indent=2))
    revision_dir = _design_dir(design_id) / "revisions" / build.revision_id
    revision_dir.mkdir(parents=True, exist_ok=True)
    (revision_dir / "build.json").write_text(json.dumps(build.model_dump(mode="json"), indent=2))
    # Snapshot the design (script + parameters) alongside the build so a
    # later restore_revision can fully rewind, not just promote artifacts.
    design = get_design_or_none(design_id)
    design_payload = design.model_dump(mode="json") if design is not None else None
    feature_graph = None
    if design is not None:
        (revision_dir / "design.json").write_text(
            json.dumps(design.model_dump(mode="json"), indent=2)
        )
        (revision_dir / "feature_graph.json").write_text(
            json.dumps(
                feature_graph := {
                    "design_id": design.id,
                    "revision_id": design.revision_id,
                    "features": [f.model_dump(mode="json") for f in design.features],
                },
                indent=2,
            )
        )
    cloud_store.save_build_payload(
        design_id,
        build_payload,
        design_payload=design_payload,
        feature_graph=feature_graph,
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
        payload = cloud_store.load_build_payload(design_id)
        if payload is None:
            return None
        path.write_text(json.dumps(payload, indent=2))
    try:
        return Build.model_validate_json(path.read_text())
    except Exception:
        return None


def get_record(design_id: str) -> DesignRecord:
    design = get_design(design_id)
    build = get_build(design_id)
    if _build_artifacts_need_regeneration(build):
        from services.codegen.engine import build_design

        build = build_design(
            design,
            targets=["stl", "glb"],
            process=design.process if design.process in {"fdm", "cnc"} else "fdm",
            printer_profile_id=design.printer_profile_id,
        )
        save_build(design.id, build)
    return DesignRecord(design=design, latest_build=build)


def _build_artifacts_need_regeneration(build: Build | None) -> bool:
    if build is None:
        return True
    for kind in ("stl", "glb"):
        artifact = build.artifacts.get(kind)
        if artifact is None:
            return True
        if artifact.url.startswith("http://") or artifact.url.startswith("https://"):
            continue
        if not Path(artifact.path).is_file():
            return True
    return False


def list_designs() -> list[Design]:
    by_id: dict[str, Design] = {}
    if not _root().exists():
        return []
    for child in _root().iterdir():
        if not child.is_dir():
            continue
        try:
            design = Design.model_validate_json((child / "design.json").read_text())
            by_id[design.id] = design
        except Exception:
            continue
    for payload in cloud_store.list_design_payloads():
        try:
            design = Design.model_validate(payload)
            by_id[design.id] = design
        except Exception:
            continue
    out = list(by_id.values())
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
        remote = cloud_store.load_conversation_payload(design_id)
        if remote is None:
            return []
        path.write_text(json.dumps(remote, indent=2))
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def save_conversation(design_id: str, messages: list[dict]) -> None:
    path = _conversation_path(design_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2))
    cloud_store.save_conversation_payload(design_id, messages)


def record_ai_usage(design_id: str, entry: dict, *, design: Design | None = None) -> dict:
    """Persist an append-only, compact cost ledger with the design."""
    design = design or get_design(design_id)
    metadata = design.metadata
    events = metadata.setdefault("ai_usage_events", [])
    if not isinstance(events, list):
        events = []
        metadata["ai_usage_events"] = events
    clean = {
        "provider": str(entry.get("provider") or "unknown"),
        "model": str(entry.get("model") or "unknown"),
        "billing_source": str(entry.get("billing_source") or "platform"),
        "input_tokens": int(entry.get("input_tokens") or 0),
        "output_tokens": int(entry.get("output_tokens") or 0),
        "cache_read_tokens": int(entry.get("cache_read_tokens") or 0),
        "cache_creation_tokens": int(entry.get("cache_creation_tokens") or 0),
        "cost_usd": float(entry.get("cost_usd") or 0),
        "ts": float(entry.get("ts") or time.time()),
    }
    events.append(clean)
    metadata["ai_usage_events"] = events[-200:]
    totals = metadata.setdefault("ai_usage_totals", {})
    if not isinstance(totals, dict):
        totals = {}
    totals.update(
        {
            "input_tokens": int(totals.get("input_tokens") or 0) + clean["input_tokens"],
            "output_tokens": int(totals.get("output_tokens") or 0) + clean["output_tokens"],
            "cache_read_tokens": int(totals.get("cache_read_tokens") or 0) + clean["cache_read_tokens"],
            "cache_creation_tokens": int(totals.get("cache_creation_tokens") or 0) + clean["cache_creation_tokens"],
            "cost_usd": float(totals.get("cost_usd") or 0) + clean["cost_usd"],
        }
    )
    metadata["ai_usage_totals"] = totals
    save_design(design)
    return totals


def list_revisions(design_id: str) -> list[dict]:
    """Enumerate the persisted revisions for a design, newest first.

    Each revision was saved by ``save_build`` to ``revisions/{rev_id}/build.json``
    so we walk that directory and read each one. Returns a compact summary
    (no full artifact list) suitable for the timeline thumbnails strip.
    """
    revisions_dir = _design_dir(design_id) / "revisions"
    by_id: dict[str, dict] = {}
    for child in revisions_dir.iterdir() if revisions_dir.exists() else []:
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
        summary = {
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
        by_id[str(summary["revision_id"])] = summary
    for remote in cloud_store.list_revision_payloads(design_id):
        build = remote.get("build") or {}
        if not isinstance(build, dict):
            continue
        revision_id = str(build.get("revision_id") or remote.get("revision_id") or "")
        if not revision_id:
            continue
        artifacts = build.get("artifacts") or {}
        glb = artifacts.get("glb") if isinstance(artifacts, dict) else None
        by_id[revision_id] = {
            "revision_id": revision_id,
            "mesh_hash": build.get("mesh_hash"),
            "bounding_box_mm": build.get("bounding_box_mm"),
            "manufacturability_status": (build.get("manufacturability") or {}).get("status"),
            "duration_ms": build.get("duration_ms"),
            "glb_url": (glb or {}).get("url") if isinstance(glb, dict) else None,
            "stat_mtime": _firestore_timestamp(remote.get("updated_at")),
        }
    out = list(by_id.values())
    out.sort(key=lambda r: r["stat_mtime"], reverse=True)
    return out


def _firestore_timestamp(value: object) -> float:
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        try:
            return float(timestamp())
        except Exception:
            return 0.0
    return 0.0


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
    if not rev_dir.exists() and cloud_store.load_revision_payload(design_id, revision_id) is None:
        return False

    import shutil

    shutil.rmtree(rev_dir, ignore_errors=True)
    cloud_store.delete_revision_payload(design_id, revision_id)
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
        remote = cloud_store.load_revision_payload(design_id, revision_id)
        if remote:
            rev_dir.mkdir(parents=True, exist_ok=True)
            remote_build = remote.get("build")
            remote_design = remote.get("design")
            remote_graph = remote.get("feature_graph")
            if isinstance(remote_build, dict):
                build_path.write_text(json.dumps(remote_build, indent=2))
            if isinstance(remote_design, dict):
                design_path.write_text(json.dumps(remote_design, indent=2))
            if isinstance(remote_graph, dict):
                (rev_dir / "feature_graph.json").write_text(json.dumps(remote_graph, indent=2))

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


def delete_design(design_id: str) -> bool:
    """Delete both the local CAD cache and durable cloud copy."""
    import shutil

    target = _root() / design_id
    existed = target.exists() or cloud_store.load_design_payload(design_id) is not None
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    cloud_store.delete_design_payload(design_id)
    return existed


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
    "delete_design",
    "prune_revisions",
    "update_design_script",
    "load_conversation",
    "save_conversation",
    "record_ai_usage",
    "new_design_id",
    "new_revision_id",
]
