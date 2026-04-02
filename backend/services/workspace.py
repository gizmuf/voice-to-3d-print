from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import HTTPException

from config import settings
from services.editable_model import (
    BuildArtifact,
    EditableModel,
    PreviewArtifact,
    WorkspaceMutation,
    WorkspaceRecord,
)
from services.native_converter import refresh_manufacturability


WORKSPACES_DIR = settings.output_dir / "workspaces"


def _workspace_dir(workspace_id: str) -> Path:
    path = WORKSPACES_DIR / workspace_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace_path(workspace_id: str) -> Path:
    return _workspace_dir(workspace_id) / "workspace.json"


def _next_revision_id() -> str:
    return uuid.uuid4().hex


def _write_record(record: WorkspaceRecord) -> WorkspaceRecord:
    path = _workspace_path(record.workspace_id)
    path.write_text(json.dumps(record.model_dump(mode="json"), indent=2))
    return record


def create_workspace(
    source: str,
    editable_model: EditableModel,
    *,
    project_id: str | None = None,
    workspace_id: str | None = None,
) -> WorkspaceRecord:
    workspace_id = workspace_id or uuid.uuid4().hex
    record = WorkspaceRecord(
        workspace_id=workspace_id,
        editable_model=editable_model.model_copy(update={"source": source}),
        project_id=project_id,
    )
    return _write_record(record)


def get_workspace(workspace_id: str) -> WorkspaceRecord:
    path = _workspace_path(workspace_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceRecord.model_validate_json(path.read_text())


def save_workspace(record: WorkspaceRecord) -> WorkspaceRecord:
    return _write_record(record)


def update_workspace(
    workspace_id: str,
    mutation: WorkspaceMutation,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id)
    model = record.editable_model.model_copy(deep=True)
    if mutation.expected_revision_id != model.revision_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Workspace revision is stale.",
                "editable_model": record.editable_model.model_dump(mode="json"),
            },
        )

    removal_ids = set(mutation.body_removes)
    if removal_ids:
        model.bodies = _remove_bodies(model.bodies, removal_ids)

    for update in mutation.body_updates:
        if not _apply_body_update(model.bodies, update.body_id, update.params):
            raise HTTPException(status_code=400, detail=f"Unknown body_id: {update.body_id}")

    if mutation.body_adds:
        model.bodies.extend(mutation.body_adds)

    if mutation.constraint_updates:
        model.constraints = mutation.constraint_updates
    if mutation.selection is not None:
        model.selection = mutation.selection

    model.manufacturability = refresh_manufacturability(model)
    model.revision_id = _next_revision_id()
    record.editable_model = model
    return save_workspace(record)


def record_preview(
    workspace_id: str,
    *,
    revision_id: str,
    glb_url: str,
    stl_url: str | None,
    validation: dict,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id)
    record.latest_preview = PreviewArtifact(
        revision_id=revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        validation=validation,
    )
    return save_workspace(record)


def record_build(
    workspace_id: str,
    *,
    revision_id: str,
    glb_url: str,
    stl_url: str,
    gcode_url: str | None,
    bundle_url: str | None,
    validation: dict,
) -> WorkspaceRecord:
    record = get_workspace(workspace_id)
    record.latest_build = BuildArtifact(
        revision_id=revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        bundle_url=bundle_url,
        validation=validation,
    )
    return save_workspace(record)


def ensure_current_revision(workspace_id: str, expected_revision_id: str) -> WorkspaceRecord:
    record = get_workspace(workspace_id)
    if record.editable_model.revision_id != expected_revision_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Workspace revision is stale.",
                "editable_model": record.editable_model.model_dump(mode="json"),
            },
        )
    return record


def _remove_bodies(bodies: list, removal_ids: set[str]) -> list:
    kept = []
    for body in bodies:
        if body.id in removal_ids:
            continue
        body.children = _remove_bodies(body.children, removal_ids)
        kept.append(body)
    return kept


def _apply_body_update(bodies: list, body_id: str, params: dict[str, float | str | bool]) -> bool:
    for body in bodies:
        if body.id == body_id:
            merged = dict(body.params)
            merged.update(params)
            body.params = merged
            return True
        if _apply_body_update(body.children, body_id, params):
            return True
    return False
