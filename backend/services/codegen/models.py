"""Pydantic models for the code-driven design engine."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


ParamType = Literal[
    "length_mm",
    "count",
    "angle_deg",
    "boolean",
    "enum",
    "ratio",
    "text",
]


class DesignParameter(BaseModel):
    name: str
    value: float | int | bool | str
    type: ParamType = "length_mm"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] | None = None
    doc: str | None = None
    locked: bool = False


FeatureCreatedBy = Literal["user_prompt", "slider", "macro", "import", "system"]


def feature_id_for_name(name: str) -> str:
    """Stable, readable ID for a named script feature."""
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_")
    return slug or "feature"


class NamedFeature(BaseModel):
    """A named segment of the design script.

    Identified by a structured comment (`# @feature: name`) plus a closing
    `# @end` marker. Lets the agent and the user surgically edit one block
    without rewriting the whole script.
    """

    id: str = ""
    name: str
    kind: str = "block"
    source: str
    parameters_used: list[str] = Field(default_factory=list)
    parent_feature_ids: list[str] = Field(default_factory=list)
    created_by: FeatureCreatedBy = "system"
    source_prompt: str | None = None
    revision_id: str = ""
    user_words: list[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            self.id = feature_id_for_name(self.name)
        if not self.user_words:
            self.user_words = [
                part
                for part in re.split(r"[_\W]+", self.name.lower())
                if part
            ][:8]


class Design(BaseModel):
    id: str
    revision_id: str
    name: str
    script: str
    parameters: list[DesignParameter] = Field(default_factory=list)
    features: list[NamedFeature] = Field(default_factory=list)
    units: Literal["mm"] = "mm"
    process: Literal["fdm", "cnc", "either"] = "either"
    parent_revision_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Selected printer profile id. None means "use the global default";
    # the value must match an entry in services.printer_profiles. Stored
    # on the design so the manufacturability check is consistent across
    # builds without the frontend resending it on every request.
    printer_profile_id: str | None = None


class BuildArtifact(BaseModel):
    kind: Literal["stl", "step", "dxf", "glb", "gcode"]
    url: str
    path: str
    bytes: int | None = None


class ManufacturabilityIssue(BaseModel):
    severity: Literal["info", "warn", "error"]
    code: str
    message: str
    location: tuple[float, float, float] | None = None
    suggestion: str | None = None
    process: Literal["fdm", "cnc", "any"] = "any"


class OrientationSuggestion(BaseModel):
    """Result of the FDM orientation search.

    Surfaced alongside the overhang issue so the UI can tell the user the part
    *would* print cleanly if reoriented, instead of just warning.
    """

    label: str
    euler_deg: tuple[float, float, float]
    overhang_fraction: float


class ManufacturabilityReport(BaseModel):
    process: Literal["fdm", "cnc", "either"]
    status: Literal["safe", "warn", "unprintable"]
    issues: list[ManufacturabilityIssue] = Field(default_factory=list)
    estimated_volume_mm3: float | None = None
    bounding_box_mm: tuple[float, float, float] | None = None
    mesh_hash: str = ""
    duration_ms: int = 0
    current_overhang_fraction: float | None = None
    suggested_orientation: OrientationSuggestion | None = None


class PrintEstimate(BaseModel):
    """Slicer-derived production estimates for FDM printing.

    Sourced from the G-code header comments PrusaSlicer writes
    (``; estimated printing time …``, ``; filament used [g] = …``). When
    G-code isn't generated (slicer unavailable, design isn't FDM-printable),
    these are all None.
    """

    filament_g: float | None = None
    filament_cm3: float | None = None
    print_minutes: float | None = None
    cost_usd: float | None = None
    cost_usd_per_g: float | None = None


class SelectionReference(BaseModel):
    topology_ref: str
    feature_id: str | None = None
    feature_name: str | None = None
    surface_type: str | None = None
    confidence: Literal["feature_face", "face", "body"] = "face"


class Build(BaseModel):
    revision_id: str
    mesh_hash: str
    bounding_box_mm: tuple[float, float, float] | None = None
    artifacts: dict[str, BuildArtifact] = Field(default_factory=dict)
    manufacturability: ManufacturabilityReport | None = None
    parameter_snapshot: dict[str, Any] = Field(default_factory=dict)
    print_estimate: PrintEstimate | None = None
    selection_map: dict[str, SelectionReference] = Field(default_factory=dict)
    duration_ms: int = 0
    log: str = ""


class DesignRecord(BaseModel):
    """On-disk representation of a design + its latest build."""

    design: Design
    latest_build: Build | None = None
