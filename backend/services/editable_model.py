from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


BodyKind = Literal[
    "body",
    "rim",
    "hole",
    "slot",
    "pocket",
    "boss",
    "linear_pattern",
    "circular_pattern",
    "fillet",
    "chamfer",
    "thickness",
]

ConstraintKind = Literal[
    "concentric",
    "aligned",
    "symmetric",
    "patterned",
    "min_wall",
    "inside_boundary",
]

WorkspaceSource = Literal["native", "step_import", "stl_reconstructed"]
ManufacturabilityStatus = Literal["safe", "risk", "invalid"]
SelectionScope = Literal["one", "all_similar", "body"]


class ConstraintNode(BaseModel):
    kind: ConstraintKind
    targets: list[str] = Field(default_factory=list)
    value: float | None = None


class SelectionState(BaseModel):
    feature_id: str
    scope: SelectionScope = "body"


class Manufacturability(BaseModel):
    status: ManufacturabilityStatus = "safe"
    messages: list[str] = Field(default_factory=list)


class BodyNode(BaseModel):
    id: str
    kind: BodyKind
    label: str
    editable: bool = True
    confidence: float = 1.0
    params: dict[str, float | str | bool] = Field(default_factory=dict)
    children: list["BodyNode"] = Field(default_factory=list)
    unsupported_reason: str | None = None


class EditableModel(BaseModel):
    id: str
    source: WorkspaceSource
    revision_id: str
    units: Literal["mm"] = "mm"
    bodies: list[BodyNode] = Field(default_factory=list)
    constraints: list[ConstraintNode] = Field(default_factory=list)
    selection: SelectionState | None = None
    manufacturability: Manufacturability = Field(default_factory=Manufacturability)


class PreviewArtifact(BaseModel):
    revision_id: str
    glb_url: str
    stl_url: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)


class BuildArtifact(BaseModel):
    revision_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None = None
    bundle_url: str | None = None
    validation: dict[str, Any] = Field(default_factory=dict)


class WorkspaceRecord(BaseModel):
    workspace_id: str
    editable_model: EditableModel
    project_id: str | None = None
    latest_preview: PreviewArtifact | None = None
    latest_build: BuildArtifact | None = None


class BodyParamUpdate(BaseModel):
    body_id: str
    params: dict[str, float | str | bool] = Field(default_factory=dict)


class WorkspaceMutation(BaseModel):
    expected_revision_id: str
    body_updates: list[BodyParamUpdate] = Field(default_factory=list)
    body_adds: list[BodyNode] = Field(default_factory=list)
    body_removes: list[str] = Field(default_factory=list)
    constraint_updates: list[ConstraintNode] = Field(default_factory=list)
    selection: SelectionState | None = None


class WorkspaceCreateRequest(BaseModel):
    prompt: str | None = None
    structured_spec: dict[str, Any] | None = None
    editable_model: EditableModel | None = None
    project_id: str | None = None
    source: WorkspaceSource = "native"

