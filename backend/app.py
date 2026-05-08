from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


_DESIGN_ID_RE = re.compile(r"^[a-f0-9]{32}$")


def _validate_design_id(design_id: str) -> str:
    """Reject design ids that aren't 32-char hex UUIDs.

    Both ``new_design_id`` and ``new_workspace_id`` produce ``uuid4().hex``,
    so anything outside that shape is either user-supplied junk or a path
    traversal attempt (``..``, slashes, control chars). All ``/design/{id}/…``
    handlers funnel through here before touching the filesystem.
    """
    if not _DESIGN_ID_RE.match(design_id or ""):
        raise HTTPException(status_code=404, detail="Design not found.")
    return design_id

from services.ai.agent import load_conversation, stream_turn
from services.ai.agent_v2 import stream_turn as stream_design_turn
from services.editability import assess as assess_editability
from services.export_bundle import export_bundle as export_bundle_service
from services.export_bundle import export_dry_run as export_bundle_dry_run
from services.printer_profiles import list_profiles as list_printer_profiles
from services.codegen.engine import (
    DesignBuildError,
    audit_then_run,
    build_design,
    build_from_sandbox_result,
    derive_named_features,
    derive_parameters,
)
from services.codegen.projection import design_to_editable_model
from services.codegen.store import (
    create_design,
    get_design,
    get_record,
    list_designs,
    load_conversation as load_design_conversation,
    save_build,
)
from services.codegen.templates import (
    get_seed_script as get_template_seed,
    list_template_ids,
    seed_for as seed_template_for,
)

from config import settings
from services.ai_edit import ai_edit_workspace_model
from services.deepgram_stt import transcribe_audio
from services.gemini_intent import extract_prompt, extract_prompt_from_image
from services.generation import GenerationResult, generate_model, generate_model_from_image
from services.job_store import (
    create_project,
    ensure_job,
    ensure_project,
    get_project,
    list_jobs_for_project,
    list_projects,
    record_error,
    update_job,
    update_project,
    upload_artifact,
)
from services.library import resolve_library_item, search_library
from services.model_editing import (
    analyze_model,
    apply_edit,
    import_model,
    preview_edit,
    public_analysis_payload,
)
from services.editable_model import EditableModel, WorkspaceCreateRequest, WorkspaceMutation
from services.editable_rebuild import export_editable_build, export_editable_preview
from services.native_converter import structured_spec_to_editable
from services.step_import import import_step_reference
from services.stl_reconstruction import reconstruct_from_analysis
from services.useful_objects import (
    build_useful_structured_spec,
    cadquery_available,
    route_mode,
)
from services.workspace import (
    create_workspace,
    ensure_current_revision,
    get_workspace,
    record_build,
    record_preview,
    update_workspace,
)
from slicer_service import ProcessResult, _slice_mesh, process_model, validate_mesh_file

app = FastAPI(title="3dprint Backend")

# CORS: `*` + `allow_credentials=True` is rejected by browsers (the spec
# disallows the combination), so the previous config silently dropped
# credentials. We default to permissive origins WITHOUT credentials, which
# matches our actual usage (no cookies, no auth headers cross-origin). To
# enable credentialed access from a known frontend, set CORS_ORIGINS to a
# comma-separated origin list and the middleware will switch to that list
# with credentials enabled.
_cors_origins_env = settings.cors_origins.strip()
if _cors_origins_env:
    _cors_origins = [origin.strip() for origin in _cors_origins_env.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

artifacts_path = Path(settings.output_dir)
artifacts_path.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=artifacts_path), name="artifacts")


def _compact_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value is not None}


def _artifact_url(upload: dict | None, path: Path, job_id: str) -> str:
    if upload and upload.get("url"):
        return upload["url"]
    return f"/artifacts/{job_id}/{path.name}"


def _workspace_artifact_url(upload: dict | None, workspace_id: str, path: Path) -> str:
    if upload and upload.get("url"):
        return upload["url"]
    return f"/artifacts/workspaces/{workspace_id}/{path.name}"


def _write_metadata(job_id: str, metadata: dict) -> None:
    metadata_path = settings.output_dir / job_id / "metadata.json"
    try:
        metadata_path.write_text(json.dumps(metadata, indent=2))
    except Exception:
        pass


class GenerateRequest(BaseModel):
    prompt: str
    provider: str | None = None
    job_id: str | None = None
    input_type: str | None = None
    prompt_raw: str | None = None
    project_id: str | None = None
    parent_job_id: str | None = None
    edit_mode: str | None = None


class GenerateResponse(BaseModel):
    job_id: str
    provider: str
    task_id: str
    glb_url: str


class ProcessRequest(BaseModel):
    glb_url: str
    job_id: str | None = None
    provider: str | None = None
    input_type: str | None = None
    prompt: str | None = None
    library_id: str | None = None
    library_source: str | None = None
    library_title: str | None = None
    project_id: str | None = None
    parent_job_id: str | None = None
    edit_mode: str | None = None
    mode: str | None = None


class ProcessResponse(BaseModel):
    job_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None
    validation: dict | None = None
    bundle_url: str | None = None


class IntentRequest(BaseModel):
    transcript: str
    job_id: str | None = None
    input_type: str | None = None
    project_id: str | None = None


class IntentResponse(BaseModel):
    job_id: str
    prompt: str


class ImageIntentResponse(BaseModel):
    job_id: str
    prompt: str


class RouteIntentRequest(BaseModel):
    raw_text: str = Field(default="")
    source: str = Field(default="text")
    mode_hint: str | None = None
    has_image: bool = False
    job_id: str | None = None
    project_id: str | None = None
    existing_spec: dict | None = None
    preview_only: bool = False


class RouteIntentResponse(BaseModel):
    job_id: str
    mode: str
    provider: str
    route_reason: str
    confidence: float
    prompt: str
    confirmation_required: bool
    structured_spec: dict | None = None


class UsefulPreviewRequest(BaseModel):
    structured_spec: dict
    job_id: str | None = None
    project_id: str | None = None
    parent_job_id: str | None = None
    revision_note: str | None = None


class UsefulPreviewResponse(BaseModel):
    job_id: str
    preview_id: str
    glb_url: str
    structured_spec: dict


class UsefulBuildRequest(BaseModel):
    structured_spec: dict
    preview_revision_id: str | None = None
    job_id: str | None = None
    project_id: str | None = None
    parent_job_id: str | None = None
    revision_note: str | None = None


class UsefulBuildResponse(BaseModel):
    job_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None = None
    validation: dict
    bundle_url: str | None = None
    structured_spec: dict


class WorkspaceResponse(BaseModel):
    workspace_id: str
    editable_model: dict
    latest_preview: dict | None = None
    latest_build: dict | None = None


class WorkspacePreviewRequest(BaseModel):
    expected_revision_id: str


class WorkspacePreviewResponse(BaseModel):
    workspace_id: str
    revision_id: str
    glb_url: str
    validation: dict


class WorkspaceBuildRequest(BaseModel):
    expected_revision_id: str


class WorkspaceAiEditRequest(BaseModel):
    body_id: str
    prompt: str
    expected_revision_id: str


class WorkspaceBuildResponse(BaseModel):
    workspace_id: str
    revision_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None = None
    bundle_url: str | None = None
    validation: dict


class ImportModelResponse(BaseModel):
    job_id: str
    model_id: str
    source_stl_url: str
    source_glb_url: str
    analysis: dict
    reconstruction_mode: str | None = None
    editable_model: dict | None = None


class ImportStepResponse(BaseModel):
    workspace_id: str
    editable_model: dict
    glb_url: str
    import_mode: str


class AnalyzeModelRequest(BaseModel):
    model_id: str
    revision_id: str | None = None


class AnalyzeModelResponse(BaseModel):
    model_id: str
    analysis: dict


class EditPreviewRequest(BaseModel):
    model_id: str
    parent_revision_id: str | None = None
    selection: dict | None = None
    edit_request: dict | None = None
    target_id: str | None = None
    params: dict | None = None
    prompt: str | None = None
    job_id: str | None = None
    project_id: str | None = None


class EditPreviewResponse(BaseModel):
    job_id: str
    preview_id: str
    model_id: str
    glb_url: str
    stl_url: str
    analysis: dict
    structured_edit: dict
    validation: dict
    warnings: list[str]


class ApplyEditRequest(BaseModel):
    model_id: str
    preview_id: str | None = None
    preview_revision_id: str | None = None
    parent_revision_id: str | None = None
    selection: dict | None = None
    edit_request: dict | None = None
    target_id: str | None = None
    params: dict | None = None
    prompt: str | None = None
    job_id: str | None = None
    project_id: str | None = None


class ApplyEditResponse(BaseModel):
    job_id: str
    model_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None = None
    validation: dict
    bundle_url: str | None = None
    analysis: dict
    structured_edit: dict
    warnings: list[str]


class ProjectCreateRequest(BaseModel):
    name: str | None = None


class ProjectResponse(BaseModel):
    project: dict


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    current_job_id: str | None = None


class ProjectsResponse(BaseModel):
    items: list[dict]


class ProjectDetailResponse(BaseModel):
    project: dict
    jobs: list[dict]


class STTResponse(BaseModel):
    transcript: str


@app.get("/telemetry/tool-summary")
def telemetry_tool_summary(token: str | None = None) -> dict:
    """Per-tool success/failure aggregates from production telemetry.

    Hidden behind ``PULSAI_ADMIN_TOKEN`` to avoid leaking tool call counts
    publicly. When the env var is unset the endpoint is unreachable.
    """
    if not settings.admin_token:
        raise HTTPException(status_code=404, detail="not found")
    if token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")
    from services.ai.telemetry import summarize_tool_calls

    return summarize_tool_calls()


@app.get("/health")
def health() -> dict:
    trellis2_text_enabled = bool(settings.trellis2_api_url and settings.trellis2_text_endpoint)
    trellis2_image_enabled = bool(settings.trellis2_api_url and settings.trellis2_image_endpoint)
    triposr_enabled = bool(settings.triposr_root and Path(settings.triposr_root).exists())
    slicer_ready = Path(settings.prusaslicer_path).exists()
    providers = {
        "meshy": {"enabled": bool(settings.meshy_api_key), "cost": "paid", "modes": ["text", "image"]},
        "tripo": {"enabled": bool(settings.tripo_api_key), "cost": "paid", "modes": ["text", "image"]},
        "trellis2": {
            "enabled": trellis2_text_enabled or trellis2_image_enabled,
            "cost": "gpu",
            "modes": [mode for mode, enabled in (("text", trellis2_text_enabled), ("image", trellis2_image_enabled)) if enabled],
        },
        "triposr": {"enabled": triposr_enabled, "cost": "local", "modes": ["image"]},
        "library_local": {"enabled": True, "cost": "free", "modes": ["search"]},
        "library_sketchfab": {"enabled": bool(settings.sketchfab_api_token), "cost": "token", "modes": ["search"]},
    }
    warnings = []
    if not settings.meshy_api_key:
        warnings.append("MESHY_API_KEY missing")
    if not settings.tripo_api_key:
        warnings.append("TRIPO_API_KEY missing")
    if not trellis2_text_enabled and not trellis2_image_enabled:
        warnings.append("TRELLIS2_API_URL/TRELLIS2_*_ENDPOINT missing")
    if not slicer_ready:
        warnings.append("PRUSASLICER_PATH missing")
    return {
        "ok": True,
        "providers": providers,
        "warnings": warnings,
        "router_ready": True,
        "cad_ready": cadquery_available(),
        "preview_ready": True,
        "slicer_ready": slicer_ready,
        "sketchfab_enabled": bool(settings.sketchfab_api_token),
    }


@app.post("/route-intent", response_model=RouteIntentResponse)
async def route_intent_endpoint(request: RouteIntentRequest) -> RouteIntentResponse:
    job_id = request.job_id or uuid.uuid4().hex
    route = route_mode(
        request.raw_text,
        source=request.source,
        mode_hint=request.mode_hint,
        has_image=request.has_image,
    )

    prompt = request.raw_text.strip()
    structured_spec = None
    confirmation_required = route["mode"] == "useful"

    if request.preview_only:
        return RouteIntentResponse(
            job_id=job_id,
            mode=route["mode"],
            provider=route["provider"],
            route_reason=route["route_reason"],
            confidence=route["confidence"],
            prompt=prompt,
            confirmation_required=False,
            structured_spec=None,
        )

    if route["mode"] == "useful":
        if route.get("template_id") is None:
            raise HTTPException(status_code=422, detail=route["route_reason"])
        try:
            structured_spec = build_useful_structured_spec(
                request.raw_text,
                source=request.source,
                existing_spec=request.existing_spec,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        prompt = structured_spec["source_inputs"]["text"]
    else:
        if request.raw_text.strip():
            try:
                prompt = await extract_prompt(request.raw_text) or request.raw_text.strip()
            except Exception:
                prompt = request.raw_text.strip()

    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "routed",
                "mode": route["mode"],
                "route.provider": route["provider"],
                "route.reason": route["route_reason"],
                "route.confidence": route["confidence"],
                "input.type": request.source,
                "input.prompt_raw": request.raw_text,
                "input.prompt_final": prompt,
                "project_id": request.project_id,
                "template_id": structured_spec.get("template_id") if structured_spec else None,
                "structured_spec": structured_spec,
            }
        ),
    )

    return RouteIntentResponse(
        job_id=job_id,
        mode=route["mode"],
        provider=route["provider"],
        route_reason=route["route_reason"],
        confidence=route["confidence"],
        prompt=prompt,
        confirmation_required=confirmation_required,
        structured_spec=structured_spec,
    )


@app.post("/workspace/create", response_model=WorkspaceResponse)
def create_workspace_endpoint(request: WorkspaceCreateRequest) -> WorkspaceResponse:
    if request.editable_model is not None:
        editable_model = request.editable_model
    elif request.structured_spec is not None:
        editable_model = structured_spec_to_editable(request.structured_spec)
    elif request.prompt:
        try:
            structured_spec = build_useful_structured_spec(request.prompt, source="text")
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        editable_model = structured_spec_to_editable(structured_spec)
    else:
        raise HTTPException(status_code=400, detail="Workspace create requires editable_model, structured_spec, or prompt.")

    record = create_workspace(request.source, editable_model, project_id=request.project_id)
    return WorkspaceResponse(
        workspace_id=record.workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        latest_preview=record.latest_preview.model_dump(mode="json") if record.latest_preview else None,
        latest_build=record.latest_build.model_dump(mode="json") if record.latest_build else None,
    )


@app.get("/workspace/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace_endpoint(workspace_id: str) -> WorkspaceResponse:
    _validate_design_id(workspace_id)
    record = get_workspace(workspace_id)
    return WorkspaceResponse(
        workspace_id=record.workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        latest_preview=record.latest_preview.model_dump(mode="json") if record.latest_preview else None,
        latest_build=record.latest_build.model_dump(mode="json") if record.latest_build else None,
    )


@app.post("/workspace/{workspace_id}/mutate", response_model=WorkspaceResponse)
def mutate_workspace_endpoint(workspace_id: str, request: WorkspaceMutation) -> WorkspaceResponse:
    _validate_design_id(workspace_id)
    record = update_workspace(workspace_id, request)
    return WorkspaceResponse(
        workspace_id=record.workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        latest_preview=record.latest_preview.model_dump(mode="json") if record.latest_preview else None,
        latest_build=record.latest_build.model_dump(mode="json") if record.latest_build else None,
    )


@app.post("/workspace/{workspace_id}/preview", response_model=WorkspacePreviewResponse)
def preview_workspace_endpoint(workspace_id: str, request: WorkspacePreviewRequest) -> WorkspacePreviewResponse:
    _validate_design_id(workspace_id)
    record = ensure_current_revision(workspace_id, request.expected_revision_id)
    workspace_dir = settings.output_dir / "workspaces" / workspace_id
    try:
        glb_path, stl_path, validation = export_editable_preview(record.editable_model, workspace_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(workspace_id, glb_path)
    stl_upload = upload_artifact(workspace_id, stl_path)
    glb_url = _workspace_artifact_url(glb_upload, workspace_id, glb_path)
    stl_url = _workspace_artifact_url(stl_upload, workspace_id, stl_path)
    record_preview(
        workspace_id,
        revision_id=record.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        validation=validation,
    )
    return WorkspacePreviewResponse(
        workspace_id=workspace_id,
        revision_id=record.editable_model.revision_id,
        glb_url=glb_url,
        validation=validation,
    )


@app.post("/workspace/{workspace_id}/build", response_model=WorkspaceBuildResponse)
def build_workspace_endpoint(workspace_id: str, request: WorkspaceBuildRequest) -> WorkspaceBuildResponse:
    _validate_design_id(workspace_id)
    record = ensure_current_revision(workspace_id, request.expected_revision_id)
    workspace_dir = settings.output_dir / "workspaces" / workspace_id
    try:
        glb_path, stl_path, validation = export_editable_build(record.editable_model, workspace_dir)
        gcode_generated = _slice_mesh(stl_path, workspace_dir / "output.gcode")
        validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
        gcode_path = workspace_dir / "output.gcode" if gcode_generated else None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(workspace_id, glb_path)
    stl_upload = upload_artifact(workspace_id, stl_path)
    gcode_upload = upload_artifact(workspace_id, gcode_path) if gcode_path else None
    glb_url = _workspace_artifact_url(glb_upload, workspace_id, glb_path)
    stl_url = _workspace_artifact_url(stl_upload, workspace_id, stl_path)
    gcode_url = _workspace_artifact_url(gcode_upload, workspace_id, gcode_path) if gcode_path else None

    bundle_path = workspace_dir / "bundle.zip"
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in (glb_path, stl_path, gcode_path):
            if path and path.exists():
                archive.write(path, arcname=path.name)
    bundle_url = f"/artifacts/workspaces/{workspace_id}/{bundle_path.name}" if bundle_path.exists() else None

    record_build(
        workspace_id,
        revision_id=record.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        bundle_url=bundle_url,
        validation=validation,
    )
    return WorkspaceBuildResponse(
        workspace_id=workspace_id,
        revision_id=record.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        bundle_url=bundle_url,
        validation=validation,
    )


@app.post("/workspace/{workspace_id}/ai-edit", response_model=WorkspaceResponse)
async def ai_edit_workspace_endpoint(workspace_id: str, request: WorkspaceAiEditRequest) -> WorkspaceResponse:
    _validate_design_id(workspace_id)
    record = ensure_current_revision(workspace_id, request.expected_revision_id)
    param_changes = await ai_edit_workspace_model(record.editable_model, request.body_id, request.prompt)
    updated = update_workspace(
        workspace_id,
        WorkspaceMutation(
            expected_revision_id=request.expected_revision_id,
            body_updates=[{"body_id": request.body_id, "params": param_changes}],
        ),
    )
    return WorkspaceResponse(
        workspace_id=updated.workspace_id,
        editable_model=updated.editable_model.model_dump(mode="json"),
        latest_preview=updated.latest_preview.model_dump(mode="json") if updated.latest_preview else None,
        latest_build=updated.latest_build.model_dump(mode="json") if updated.latest_build else None,
    )


@app.post("/preview-useful", response_model=UsefulPreviewResponse)
def preview_useful_endpoint(request: UsefulPreviewRequest) -> UsefulPreviewResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "drafting",
                "mode": "useful",
                "provider": "useful-cad",
                "project_id": request.project_id,
                "parent_job_id": request.parent_job_id,
                "template_id": request.structured_spec.get("template_id"),
                "structured_spec": request.structured_spec,
                "revision_notes": [request.revision_note] if request.revision_note else None,
            }
        ),
    )

    try:
        editable_model = structured_spec_to_editable(request.structured_spec)
        workspace = create_workspace("native", editable_model, project_id=request.project_id, workspace_id=job_id)
        preview_glb_path, preview_stl_path, validation = export_editable_preview(
            workspace.editable_model,
            settings.output_dir / "workspaces" / workspace.workspace_id,
        )
    except Exception as exc:
        record_error(job_id, "preview-useful", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, preview_glb_path)
    stl_upload = upload_artifact(job_id, preview_stl_path)
    glb_url = _workspace_artifact_url(glb_upload, workspace.workspace_id, preview_glb_path)
    stl_url = _workspace_artifact_url(stl_upload, workspace.workspace_id, preview_stl_path)
    record_preview(
        workspace.workspace_id,
        revision_id=workspace.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        validation=validation,
    )
    update_job(
        job_id,
        {
            "status": "preview_ready",
            "preview_artifacts.glb_url": glb_url,
            "preview_artifacts.glb_size": glb_upload["size"] if glb_upload else preview_glb_path.stat().st_size,
        },
    )

    _write_metadata(
        job_id,
        {
            "job_id": job_id,
            "mode": "useful",
            "template_id": request.structured_spec.get("template_id"),
            "structured_spec": request.structured_spec,
            "preview_artifacts": {"glb_url": glb_url},
            "revision_note": request.revision_note,
        },
    )

    return UsefulPreviewResponse(
        job_id=job_id,
        preview_id=workspace.workspace_id,
        glb_url=glb_url,
        structured_spec=request.structured_spec,
    )


@app.post("/build-useful", response_model=UsefulBuildResponse)
def build_useful_endpoint(request: UsefulBuildRequest) -> UsefulBuildResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "building",
                "mode": "useful",
                "provider": "useful-cad",
                "project_id": request.project_id,
                "parent_job_id": request.parent_job_id or request.preview_revision_id,
                "template_id": request.structured_spec.get("template_id"),
                "structured_spec": request.structured_spec,
                "user_confirmed_spec": request.structured_spec,
                "revision_notes": [request.revision_note] if request.revision_note else None,
            }
        ),
    )

    try:
        editable_model = structured_spec_to_editable(request.structured_spec)
        workspace = create_workspace("native", editable_model, project_id=request.project_id, workspace_id=job_id)
        build_glb_path, build_stl_path, validation = export_editable_build(
            workspace.editable_model,
            settings.output_dir / "workspaces" / workspace.workspace_id,
        )
        gcode_generated = _slice_mesh(build_stl_path, build_stl_path.parent / "output.gcode")
        validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
        gcode_path = build_stl_path.parent / "output.gcode" if gcode_generated else None
    except Exception as exc:
        record_error(job_id, "build-useful", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, build_glb_path)
    stl_upload = upload_artifact(job_id, build_stl_path)
    gcode_upload = upload_artifact(job_id, gcode_path) if gcode_path else None
    glb_url = _workspace_artifact_url(glb_upload, workspace.workspace_id, build_glb_path)
    stl_url = _workspace_artifact_url(stl_upload, workspace.workspace_id, build_stl_path)
    gcode_url = _workspace_artifact_url(gcode_upload, workspace.workspace_id, gcode_path) if gcode_path else None

    _write_metadata(
        job_id,
        {
            "job_id": job_id,
            "mode": "useful",
            "template_id": request.structured_spec.get("template_id"),
            "structured_spec": request.structured_spec,
            "artifacts": {
                "glb_url": glb_url,
                "stl_url": stl_url,
                "gcode_url": gcode_url,
            },
            "validation": validation,
            "preview_revision_id": request.preview_revision_id,
            "revision_note": request.revision_note,
        },
    )

    bundle_path = settings.output_dir / "workspaces" / workspace.workspace_id / "bundle.zip"
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in (build_glb_path, build_stl_path, gcode_path):
            if path and path.exists():
                archive.write(path, arcname=path.name)
    bundle_url = f"/artifacts/workspaces/{workspace.workspace_id}/{bundle_path.name}" if bundle_path.exists() else None
    record_build(
        workspace.workspace_id,
        revision_id=workspace.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        bundle_url=bundle_url,
        validation=validation,
    )

    update_job(
        job_id,
        {
            "status": "ready" if validation.get("validation_status") != "failed" else "needs_review",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "artifacts.gcode_url": gcode_url,
            "validation": validation,
            "preview_artifacts.glb_url": f"/artifacts/workspaces/{workspace.workspace_id}/preview.glb"
            if (build_glb_path.parent / "preview.glb").exists()
            else None,
        },
    )
    if request.project_id:
        update_project(request.project_id, {"current_job_id": job_id})

    return UsefulBuildResponse(
        job_id=job_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        validation=validation,
        bundle_url=bundle_url,
        structured_spec=request.structured_spec,
    )


@app.post("/import-step", response_model=ImportStepResponse)
async def import_step_endpoint(
    model: UploadFile = File(...),
    project_id: str | None = Form(None),
) -> ImportStepResponse:
    filename = (model.filename or "upload.step").strip() or "upload.step"
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="Only STEP files are supported at this endpoint.")

    content = await model.read()
    workspace_id = uuid.uuid4().hex
    try:
        imported = import_step_reference(content, filename, settings.output_dir / "workspaces" / workspace_id)
        record = create_workspace("step_import", imported.workspace_model, project_id=project_id, workspace_id=workspace_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(workspace_id, imported.glb_path)
    glb_url = _workspace_artifact_url(glb_upload, workspace_id, imported.glb_path)
    record_preview(
        workspace_id,
        revision_id=record.editable_model.revision_id,
        glb_url=glb_url,
        stl_url=_workspace_artifact_url(None, workspace_id, imported.stl_path),
        validation={"status": "reference"},
    )
    return ImportStepResponse(
        workspace_id=workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        glb_url=glb_url,
        import_mode=imported.import_mode,
    )


@app.post("/import-model", response_model=ImportModelResponse)
async def import_model_endpoint(
    model: UploadFile = File(...),
    job_id: str | None = Form(None),
    project_id: str | None = Form(None),
) -> ImportModelResponse:
    filename = (model.filename or "upload.stl").strip() or "upload.stl"
    if not filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only STL files are supported in the precision edit flow.")

    job_id = job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "importing",
                "mode": "existing-model-edit",
                "revision_type": "import",
                "provider": "uploaded-stl",
                "project_id": project_id,
                "input.type": "stl-upload",
                "input.file_name": filename,
            }
        ),
    )

    try:
        content = await model.read()
        imported = import_model(content, filename, job_id)
    except Exception as exc:
        record_error(job_id, "import-model", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    analysis_payload = public_analysis_payload(imported.analysis)
    reconstructed_model, reconstruction_mode = reconstruct_from_analysis(analysis_payload)

    stl_url = _artifact_url(None, imported.stl_path, job_id)
    glb_url = _artifact_url(None, imported.glb_path, job_id)

    update_job(
        job_id,
        {
            "status": "imported",
            "model_id": imported.model_id,
            "source_model.stl_url": stl_url,
            "source_model.glb_url": glb_url,
            "mesh_analysis": analysis_payload,
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
        },
    )
    if project_id:
        update_project(project_id, {"current_job_id": job_id})

    _write_metadata(
        job_id,
        {
            "job_id": job_id,
            "model_id": imported.model_id,
            "mode": "existing-model-edit",
            "revision_type": "import",
            "source_model": {"stl_url": stl_url, "glb_url": glb_url},
            "mesh_analysis": analysis_payload,
        },
    )

    return ImportModelResponse(
        job_id=job_id,
        model_id=imported.model_id,
        source_stl_url=stl_url,
        source_glb_url=glb_url,
        analysis=analysis_payload,
        reconstruction_mode=reconstruction_mode,
        editable_model=reconstructed_model.model_dump(mode="json") if reconstructed_model else None,
    )


@app.post("/analyze-model", response_model=AnalyzeModelResponse)
def analyze_model_endpoint(request: AnalyzeModelRequest) -> AnalyzeModelResponse:
    try:
        analysis = analyze_model(request.model_id, request.revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return AnalyzeModelResponse(model_id=request.model_id, analysis=public_analysis_payload(analysis))


@app.post("/preview-edit", response_model=EditPreviewResponse)
def preview_edit_endpoint(request: EditPreviewRequest) -> EditPreviewResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "drafting",
                "mode": "existing-model-edit",
                "revision_type": "preview_edit",
                "provider": "cadquery-meshlib-edit",
                "project_id": request.project_id,
                "parent_job_id": request.parent_revision_id,
                "model_id": request.model_id,
                "selection": request.selection,
                "edit_request": request.edit_request,
                "target_id": request.target_id,
                "params": request.params,
                "input.prompt_final": request.prompt,
            }
        ),
    )

    try:
        preview = preview_edit(
            model_id=request.model_id,
            job_id=job_id,
            selection=request.selection,
            edit_request=request.edit_request,
            target_id=request.target_id,
            params=request.params,
            prompt=request.prompt,
            parent_revision_id=request.parent_revision_id,
        )
    except Exception as exc:
        record_error(job_id, "preview-edit", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_url = _artifact_url(None, preview.glb_path, job_id)
    stl_url = _artifact_url(None, preview.stl_path, job_id)
    analysis_payload = public_analysis_payload(preview.analysis)

    update_job(
        job_id,
        {
            "status": "preview_ready",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "mesh_analysis": analysis_payload,
            "selection": request.selection,
            "edit_request": request.edit_request,
            "target_id": request.target_id,
            "params": request.params,
            "structured_edit": preview.structured_edit,
            "validation": preview.validation,
            "fallback_strategy_used": preview.fallback_strategy_used,
        },
    )

    _write_metadata(
        job_id,
        {
            "job_id": job_id,
            "model_id": request.model_id,
            "mode": "existing-model-edit",
            "revision_type": "preview_edit",
            "selection": request.selection,
            "edit_request": request.edit_request,
            "target_id": request.target_id,
            "params": request.params,
            "structured_edit": preview.structured_edit,
            "mesh_analysis": analysis_payload,
            "preview_artifacts": {"glb_url": glb_url, "stl_url": stl_url},
            "validation": preview.validation,
            "fallback_strategy_used": preview.fallback_strategy_used,
        },
    )

    return EditPreviewResponse(
        job_id=job_id,
        preview_id=job_id,
        model_id=request.model_id,
        glb_url=glb_url,
        stl_url=stl_url,
        analysis=analysis_payload,
        structured_edit=preview.structured_edit,
        validation=preview.validation,
        warnings=preview.warnings,
    )


@app.post("/apply-edit", response_model=ApplyEditResponse)
def apply_edit_endpoint(request: ApplyEditRequest) -> ApplyEditResponse:
    job_id = request.job_id or uuid.uuid4().hex
    preview_revision_id = request.preview_id or request.preview_revision_id
    if not preview_revision_id:
        raise HTTPException(status_code=400, detail="Apply requires a successful preview_id.")

    parent_revision_id = preview_revision_id or request.parent_revision_id
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "building",
                "mode": "existing-model-edit",
                "revision_type": "applied_edit",
                "provider": "cadquery-meshlib-edit",
                "project_id": request.project_id,
                "parent_job_id": parent_revision_id,
                "model_id": request.model_id,
                "selection": request.selection,
                "edit_request": request.edit_request,
                "target_id": request.target_id,
                "params": request.params,
                "input.prompt_final": request.prompt,
            }
        ),
    )

    try:
        if preview_revision_id:
            source_dir = settings.output_dir / preview_revision_id
            source_stl = source_dir / "model.stl"
            source_glb = source_dir / "preview.glb"
            if not source_stl.exists():
                raise FileNotFoundError("Preview STL was not found for apply-edit.")
            if not source_glb.exists():
                source_glb = source_dir / "model.glb"
            if not source_glb.exists():
                raise FileNotFoundError("Preview GLB was not found for apply-edit.")

            target_dir = settings.output_dir / job_id
            target_dir.mkdir(parents=True, exist_ok=True)
            final_stl = target_dir / "model.stl"
            final_glb = target_dir / "model.glb"
            shutil.copy(source_stl, final_stl)
            shutil.copy(source_glb, final_glb)
            validation = validate_mesh_file(final_stl)
            analysis = analyze_model(request.model_id, preview_revision_id)
            structured_edit = (
                {
                    "target_id": request.target_id,
                    "params": request.params or {},
                    "preview_id": preview_revision_id,
                }
                if request.target_id
                else dict(request.edit_request or {})
            )
            fallback_strategy_used = None
            gcode_generated = _slice_mesh(final_stl, target_dir / "output.gcode")
            validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
            gcode_path = target_dir / "output.gcode" if gcode_generated else None

            applied = type("AppliedPreview", (), {})()
            applied.glb_path = final_glb
            applied.stl_path = final_stl
            applied.analysis = analysis
            applied.structured_edit = structured_edit
            applied.validation = validation
            applied.warnings = validation.get("warnings", [])
            applied.fallback_strategy_used = fallback_strategy_used
        else:
            applied = apply_edit(
                model_id=request.model_id,
                job_id=job_id,
                selection=request.selection,
                edit_request=request.edit_request,
                target_id=request.target_id,
                params=request.params,
                prompt=request.prompt,
                parent_revision_id=parent_revision_id,
            )
            gcode_generated = _slice_mesh(applied.stl_path, applied.stl_path.parent / "output.gcode")
            applied.validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
            gcode_path = applied.stl_path.parent / "output.gcode" if gcode_generated else None
    except Exception as exc:
        record_error(job_id, "apply-edit", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_url = _artifact_url(None, applied.glb_path, job_id)
    stl_url = _artifact_url(None, applied.stl_path, job_id)
    gcode_url = _artifact_url(None, gcode_path, job_id) if gcode_path else None
    analysis_payload = public_analysis_payload(applied.analysis)

    update_job(
        job_id,
        {
            "status": "ready" if applied.validation.get("validation_status") != "failed" else "needs_review",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "artifacts.gcode_url": gcode_url,
            "mesh_analysis": analysis_payload,
            "selection": request.selection,
            "edit_request": request.edit_request,
            "preview_id": preview_revision_id,
            "structured_edit": applied.structured_edit,
            "validation": applied.validation,
            "fallback_strategy_used": applied.fallback_strategy_used,
        },
    )
    if request.project_id:
        update_project(request.project_id, {"current_job_id": job_id})

    _write_metadata(
        job_id,
        {
            "job_id": job_id,
            "model_id": request.model_id,
            "mode": "existing-model-edit",
            "revision_type": "applied_edit",
            "preview_id": preview_revision_id,
            "selection": request.selection,
            "edit_request": request.edit_request,
            "structured_edit": applied.structured_edit,
            "mesh_analysis": analysis_payload,
            "artifacts": {"glb_url": glb_url, "stl_url": stl_url, "gcode_url": gcode_url},
            "validation": applied.validation,
            "fallback_strategy_used": applied.fallback_strategy_used,
        },
    )

    bundle_response = bundle(job_id)
    return ApplyEditResponse(
        job_id=job_id,
        model_id=request.model_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        validation=applied.validation,
        bundle_url=bundle_response.get("url"),
        analysis=analysis_payload,
        structured_edit=applied.structured_edit,
        warnings=applied.warnings,
    )


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest) -> GenerateResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "generating",
                "provider": (request.provider or settings.threed_provider).lower(),
                "input.type": request.input_type,
                "input.prompt_raw": request.prompt_raw,
                "input.prompt_final": request.prompt,
                "project_id": request.project_id,
                "parent_job_id": request.parent_job_id,
                "edit_mode": request.edit_mode,
                "mode": "creative",
            }
        ),
    )
    try:
        result: GenerationResult = await generate_model(request.prompt, provider=request.provider)
    except Exception as exc:
        record_error(job_id, "generate", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    update_job(
        job_id,
        {
            "status": "generated",
            "generation.task_id": result.task_id,
            "generation.provider": result.provider,
            "generation.glb_source_url": result.glb_url,
        },
    )
    return GenerateResponse(job_id=job_id, provider=result.provider, task_id=result.task_id, glb_url=result.glb_url)


@app.post("/generate-image", response_model=GenerateResponse)
async def generate_image(
    provider: str | None = None,
    job_id: str | None = Form(None),
    input_type: str | None = Form(None),
    project_id: str | None = Form(None),
    parent_job_id: str | None = Form(None),
    edit_mode: str | None = Form(None),
    image: UploadFile = File(...),
) -> GenerateResponse:
    job_id = job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "generating",
                "provider": (provider or settings.threed_provider).lower(),
                "input.type": input_type or "image",
                "input.image_name": image.filename,
                "input.image_content_type": image.content_type,
                "project_id": project_id,
                "parent_job_id": parent_job_id,
                "edit_mode": edit_mode,
                "mode": "creative",
            }
        ),
    )
    try:
        content = await image.read()
        update_job(job_id, {"input.image_size": len(content)})
        result: GenerationResult = await generate_model_from_image(
            content,
            image.filename or "upload.jpg",
            image.content_type or "image/jpeg",
            job_id=job_id,
            provider=provider,
        )
    except Exception as exc:
        record_error(job_id, "generate-image", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    update_job(
        job_id,
        {
            "status": "generated",
            "generation.task_id": result.task_id,
            "generation.provider": result.provider,
            "generation.glb_source_url": result.glb_url,
        },
    )
    return GenerateResponse(job_id=job_id, provider=result.provider, task_id=result.task_id, glb_url=result.glb_url)


@app.post("/process-model", response_model=ProcessResponse)
def process(request: ProcessRequest) -> ProcessResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "making_printable",
                "provider": request.provider,
                "mode": request.mode or "creative",
                "input.type": request.input_type,
                "input.prompt_final": request.prompt,
                "input.library_id": request.library_id,
                "input.library_source": request.library_source,
                "input.library_title": request.library_title,
                "project_id": request.project_id,
                "parent_job_id": request.parent_job_id,
                "edit_mode": request.edit_mode,
            }
        ),
    )
    try:
        result: ProcessResult = process_model(request.glb_url, job_id=job_id)
    except Exception as exc:
        record_error(job_id, "process-model", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, result.glb_path)
    stl_upload = upload_artifact(job_id, result.stl_path)
    gcode_upload = upload_artifact(job_id, result.gcode_path) if result.gcode_path else None

    glb_url = _artifact_url(glb_upload, result.glb_path, job_id)
    stl_url = _artifact_url(stl_upload, result.stl_path, job_id)
    gcode_url = _artifact_url(gcode_upload, result.gcode_path, job_id) if result.gcode_path else None
    bundle_response = bundle(job_id)
    bundle_url = bundle_response.get("url")

    metadata = {
        "job_id": job_id,
        "provider": request.provider,
        "mode": request.mode or "creative",
        "input_type": request.input_type,
        "prompt": request.prompt,
        "library_id": request.library_id,
        "library_source": request.library_source,
        "library_title": request.library_title,
        "project_id": request.project_id,
        "parent_job_id": request.parent_job_id,
        "edit_mode": request.edit_mode,
        "artifacts": {"glb_url": glb_url, "stl_url": stl_url, "gcode_url": gcode_url},
        "validation": result.validation,
    }
    _write_metadata(job_id, metadata)

    update_job(
        job_id,
        {
            "status": "ready",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "artifacts.gcode_url": gcode_url,
            "artifacts.glb_size": glb_upload["size"] if glb_upload else result.glb_path.stat().st_size,
            "artifacts.stl_size": stl_upload["size"] if stl_upload else result.stl_path.stat().st_size,
            "artifacts.gcode_size": gcode_upload["size"] if gcode_upload else (result.gcode_path.stat().st_size if result.gcode_path else None),
            "validation": result.validation,
        },
    )
    if request.project_id:
        update_project(request.project_id, {"current_job_id": job_id})
    return ProcessResponse(
        job_id=result.job_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        validation=result.validation,
        bundle_url=bundle_url,
    )


@app.get("/bundle/{job_id}")
def bundle(job_id: str) -> dict:
    job_dir = settings.output_dir / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    bundle_path = job_dir / "bundle.zip"
    files = [
        job_dir / "preview.glb",
        job_dir / "model.glb",
        job_dir / "model.stl",
        job_dir / "output.gcode",
        job_dir / "metadata.json",
    ]

    added = 0
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            if path.exists():
                archive.write(path, arcname=path.name)
                added += 1

    if added == 0:
        raise HTTPException(status_code=404, detail="No artifacts available for bundle.")

    return {"url": f"/artifacts/{job_id}/{bundle_path.name}"}


@app.post("/intent", response_model=IntentResponse)
async def intent(request: IntentRequest) -> IntentResponse:
    job_id = request.job_id or uuid.uuid4().hex
    prompt = await extract_prompt(request.transcript)
    if not prompt:
        record_error(job_id, "intent", "Failed to extract prompt.")
        raise HTTPException(status_code=500, detail="Failed to extract prompt.")
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "intent_ready",
                "input.type": request.input_type,
                "input.transcript": request.transcript,
                "input.prompt_final": prompt,
                "project_id": request.project_id,
            }
        ),
    )
    return IntentResponse(job_id=job_id, prompt=prompt)


@app.post("/image-intent", response_model=ImageIntentResponse)
async def image_intent(
    image: UploadFile = File(...),
    job_id: str | None = Form(None),
    input_type: str | None = Form(None),
    project_id: str | None = Form(None),
    parent_job_id: str | None = Form(None),
    edit_mode: str | None = Form(None),
) -> ImageIntentResponse:
    job_id = job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload(
            {
                "status": "extracting",
                "input.type": input_type or "image",
                "input.image_name": image.filename,
                "input.image_content_type": image.content_type,
                "project_id": project_id,
                "parent_job_id": parent_job_id,
                "edit_mode": edit_mode,
            }
        ),
    )
    try:
        content = await image.read()
        update_job(job_id, {"input.image_size": len(content)})
        prompt = await extract_prompt_from_image(content, image.content_type or "image/jpeg")
    except Exception as exc:
        record_error(job_id, "image-intent", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not prompt:
        record_error(job_id, "image-intent", "Failed to extract prompt.")
        raise HTTPException(status_code=500, detail="Failed to extract prompt.")

    update_job(job_id, {"status": "intent_ready", "input.prompt_final": prompt})
    return ImageIntentResponse(job_id=job_id, prompt=prompt)


@app.post("/projects", response_model=ProjectResponse)
def create_project_endpoint(request: ProjectCreateRequest) -> ProjectResponse:
    project = create_project(request.name)
    if not project:
        raise HTTPException(status_code=500, detail="Failed to create project.")
    return ProjectResponse(project=project)


@app.get("/projects", response_model=ProjectsResponse)
def list_projects_endpoint() -> ProjectsResponse:
    return ProjectsResponse(items=list_projects())


@app.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def project_detail(project_id: str) -> ProjectDetailResponse:
    project = get_project(project_id) or {"project_id": project_id}
    jobs = list_jobs_for_project(project_id)
    return ProjectDetailResponse(project=project, jobs=jobs)


@app.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project_endpoint(project_id: str, request: ProjectUpdateRequest) -> ProjectResponse:
    payload = _compact_payload({"name": request.name, "current_job_id": request.current_job_id})
    if payload:
        ensure_project(project_id, payload)
    project = get_project(project_id) or {"project_id": project_id}
    return ProjectResponse(project=project)


@app.post("/stt", response_model=STTResponse)
async def stt(audio: UploadFile = File(...)) -> STTResponse:
    try:
        content = await audio.read()
        transcript = await transcribe_audio(content, content_type=audio.content_type or "")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return STTResponse(transcript=transcript)


@app.get("/library/search")
async def library_search(query: str = "", provider: str = "local") -> dict:
    return {"items": await search_library(query, provider)}


@app.get("/library/resolve")
async def library_resolve(uid: str, provider: str = "local") -> dict:
    try:
        glb_url = await resolve_library_item(uid, provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not glb_url:
        raise HTTPException(status_code=404, detail="No downloadable GLB found.")
    return {"glb_url": glb_url}


# ---------------------------------------------------------------------------
# Phase 1 additions: chat agent loop, editability, export-bundle, profiles.
# ---------------------------------------------------------------------------


class WorkspaceChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    printer_profile_id: str | None = None
    selected_feature_id: str | None = None
    selected_feature_label: str | None = None


@app.post("/workspace/{workspace_id}/chat")
async def workspace_chat_endpoint(workspace_id: str, request: WorkspaceChatRequest):
    """Stream one chat turn as Server-Sent Events.

    Routes to the powerful code-driven agent (services/ai/agent_v2.py) when a
    Design exists for ``workspace_id`` — or can be auto-seeded from the
    workspace's template. Falls back to the legacy capability-matrix agent
    only when the workspace has no build123d seeder available.
    """
    _validate_design_id(workspace_id)
    from services.codegen.store import get_design_or_none

    design = get_design_or_none(workspace_id)

    if design is None:
        # Try to auto-seed a Design at the same id, using the workspace's
        # template. The user keeps their URL; the chat just gets smarter.
        try:
            workspace_record = get_workspace(workspace_id)
        except HTTPException:
            workspace_record = None

        if workspace_record is not None and workspace_record.editable_model.bodies:
            template_id = str(
                workspace_record.editable_model.bodies[0].params.get("_template_id", "")
            )
            if template_id in list_template_ids():
                seed_name, seed_script = get_template_seed(template_id)
                # Carry over the workspace's current parameter values so the new
                # script renders the same shape the user already sees.
                root_params = workspace_record.editable_model.bodies[0].params
                overrides_for_seed: dict = {}
                for body in workspace_record.editable_model.bodies:
                    for k, v in body.params.items():
                        if k.startswith("_"):
                            continue
                        if isinstance(v, (int, float, bool, str)):
                            overrides_for_seed[k] = v
                    for child in body.children:
                        for k, v in child.params.items():
                            if k.startswith("_"):
                                continue
                            if isinstance(v, (int, float, bool, str)):
                                overrides_for_seed[k] = v

                try:
                    sandbox_seed = audit_then_run(
                        script=seed_script,
                        parameter_overrides=overrides_for_seed,
                        targets=["stl", "glb"],
                    )
                except DesignBuildError:
                    sandbox_seed = None

                if sandbox_seed is not None and sandbox_seed.ok:
                    parameters = derive_parameters(sandbox_seed.payload)
                    features = derive_named_features(
                        sandbox_seed.payload,
                        seed_script,
                        created_by="import",
                    )
                    design = create_design(
                        name=str(root_params.get("_object_label") or seed_name),
                        script=seed_script,
                        parameters=parameters,
                        features=features,
                        process="fdm",
                        metadata={"template_id": template_id, "bridged_from_workspace": True},
                        design_id=workspace_id,  # same id so the URL doesn't change
                    )
                    # Relocate the audit artifacts to the design's persistent dir
                    # so /artifacts/designs/{id}/... URLs work.
                    from pathlib import Path
                    import shutil

                    persistent = settings.output_dir / "designs" / design.id
                    persistent.mkdir(parents=True, exist_ok=True)
                    relocated: dict[str, str] = {}
                    for kind, src in (sandbox_seed.payload.get("artifacts") or {}).items():
                        src_path = Path(src)
                        if not src_path.exists():
                            continue
                        dst_path = persistent / src_path.name
                        try:
                            shutil.copy2(src_path, dst_path)
                            relocated[kind] = str(dst_path)
                        except Exception:
                            continue
                    sandbox_seed.payload["artifacts"] = relocated
                    initial_build = build_from_sandbox_result(
                        design, sandbox_seed, process="fdm"
                    )
                    save_build(design.id, initial_build)

    if design is not None:
        generator = stream_design_turn(
            workspace_id,
            request.message,
            printer_profile_id=request.printer_profile_id,
            selected_feature_id=request.selected_feature_id,
            selected_feature_label=request.selected_feature_label,
        )
        return StreamingResponse(generator, media_type="text/event-stream")

    # Legacy fallback (no build123d seeder for this template — e.g. STEP imports).
    generator = stream_turn(
        workspace_id,
        request.message,
        printer_profile_id=request.printer_profile_id,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@app.get("/workspace/{workspace_id}/conversation")
def workspace_conversation_endpoint(workspace_id: str) -> dict:
    _validate_design_id(workspace_id)
    return {"workspace_id": workspace_id, "messages": load_conversation(workspace_id)}


@app.get("/workspace/{workspace_id}/editability")
def workspace_editability_endpoint(workspace_id: str) -> dict:
    _validate_design_id(workspace_id)
    record = get_workspace(workspace_id)
    assessment = assess_editability(record.editable_model)
    return {
        "workspace_id": workspace_id,
        "revision_id": record.editable_model.revision_id,
        "assessment": assessment.model_dump(),
    }


class WorkspaceExportBundleRequest(BaseModel):
    expected_revision_id: str
    printer_profile_id: str | None = None
    model_name: str | None = None


class WorkspaceExportBundleResponse(BaseModel):
    workspace_id: str
    revision_id: str
    bundle_url: str
    glb_url: str
    stl_url: str | None
    gcode_url: str | None
    manifest: dict


@app.post(
    "/workspace/{workspace_id}/export-bundle",
    response_model=WorkspaceExportBundleResponse,
)
def workspace_export_bundle_endpoint(
    workspace_id: str, request: WorkspaceExportBundleRequest
) -> WorkspaceExportBundleResponse:
    _validate_design_id(workspace_id)
    result = export_bundle_service(
        workspace_id,
        request.expected_revision_id,
        printer_profile_id=request.printer_profile_id,
        model_name=request.model_name,
    )
    return WorkspaceExportBundleResponse(
        workspace_id=result.workspace_id,
        revision_id=result.revision_id,
        bundle_url=result.bundle_url,
        glb_url=result.glb_url,
        stl_url=result.stl_url,
        gcode_url=result.gcode_url,
        manifest=result.manifest,
    )


@app.get("/workspace/{workspace_id}/export-bundle/dry-run")
def workspace_export_bundle_dry_run_endpoint(workspace_id: str) -> dict:
    _validate_design_id(workspace_id)
    return export_bundle_dry_run(workspace_id)


@app.get("/printer-profiles")
def printer_profiles_endpoint() -> dict:
    from services.printer_profiles import get_profile

    return {
        "default": get_profile(settings.default_printer_profile_id).id,
        "profiles": [p.model_dump() for p in list_printer_profiles()],
    }


# ---------------------------------------------------------------------------
# Code-driven CAD engine — Design + powerful agent loop.
# ---------------------------------------------------------------------------


class DesignCreateRequest(BaseModel):
    prompt: str | None = None
    template_id: str | None = None
    name: str | None = None
    script: str | None = None
    process: str = "either"


class DesignCreateResponse(BaseModel):
    design_id: str
    revision_id: str
    name: str
    template_id: str | None
    script: str
    parameters: list[dict]
    features: list[dict]
    initial_build: dict | None
    editable_model: dict


def _seed_design_record(request: DesignCreateRequest):
    if request.script:
        name = request.name or "Custom design"
        return None, name, request.script
    if request.template_id:
        if request.template_id not in list_template_ids():
            raise HTTPException(status_code=400, detail=f"Unknown template_id: {request.template_id}")
        display, script = get_template_seed(request.template_id)
        return request.template_id, request.name or display, script
    if request.prompt:
        tid, display, script = seed_template_for(request.prompt)
        return tid, request.name or display, script
    raise HTTPException(
        status_code=400,
        detail="Provide one of: prompt, template_id, or script.",
    )


@app.post("/design/create", response_model=DesignCreateResponse)
def design_create_endpoint(request: DesignCreateRequest) -> DesignCreateResponse:
    template_id, name, script = _seed_design_record(request)

    try:
        # Initial seed only needs STL + GLB so the user sees the model fast.
        # STEP export is heavy (OCCT serializer on hundreds of holes); request
        # it explicitly via /design/{id}/build when needed for CNC handoff.
        sandbox_result = audit_then_run(script=script, targets=["stl", "glb"])
    except DesignBuildError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": "Seed script failed AST audit.", "errors": exc.audit_errors},
        ) from exc
    if not sandbox_result.ok:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Seed script failed to build.",
                "error": sandbox_result.payload.get("error"),
                "traceback": sandbox_result.payload.get("traceback"),
            },
        )

    parameters = derive_parameters(sandbox_result.payload)
    features = derive_named_features(sandbox_result.payload, script, created_by="system")

    design = create_design(
        name=name,
        script=script,
        parameters=parameters,
        features=features,
        process=request.process,
        metadata={"template_id": template_id} if template_id else {},
    )

    # Reuse the sandbox payload from the audit run instead of re-executing the
    # script. Move artifacts from the throwaway /tmp dir into the design's
    # persistent workdir so URLs stay stable.
    from pathlib import Path
    import shutil

    persistent = settings.output_dir / "designs" / design.id
    persistent.mkdir(parents=True, exist_ok=True)
    relocated_artifacts: dict[str, str] = {}
    for kind, src in (sandbox_result.payload.get("artifacts") or {}).items():
        src_path = Path(src)
        if not src_path.exists():
            continue
        dst_path = persistent / src_path.name
        try:
            shutil.copy2(src_path, dst_path)
            relocated_artifacts[kind] = str(dst_path)
        except Exception:
            continue
    sandbox_result.payload["artifacts"] = relocated_artifacts

    build = build_from_sandbox_result(design, sandbox_result, process="fdm")
    save_build(design.id, build)

    editable_model = design_to_editable_model(design, build)
    return DesignCreateResponse(
        design_id=design.id,
        revision_id=design.revision_id,
        name=design.name,
        template_id=template_id,
        script=design.script,
        parameters=[p.model_dump() for p in design.parameters],
        features=[f.model_dump() for f in design.features],
        initial_build={
            "revision_id": build.revision_id,
            "mesh_hash": build.mesh_hash,
            "bounding_box_mm": build.bounding_box_mm,
            "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
            "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
        },
        editable_model=editable_model.model_dump(mode="json"),
    )


class DesignImportSTLResponse(BaseModel):
    design_id: str
    revision_id: str
    name: str
    script: str
    parameters: list[dict]
    features: list[dict]
    initial_build: dict | None


@app.post("/design/import-stl", response_model=DesignImportSTLResponse)
async def design_import_stl_endpoint(
    model: UploadFile = File(...),
    name: str | None = Form(None),
    process: str = Form("fdm"),
) -> DesignImportSTLResponse:
    """Upload an STL or STEP file and seed an editable design.

    - ``.stl`` → loaded as ``imported_mesh`` (trimesh.Trimesh) for mesh-level ops.
    - ``.step`` / ``.stp`` → loaded as ``imported_part`` (build123d Compound) for B-rep ops.

    The endpoint name is kept as ``import-stl`` for backward compatibility;
    both file types are accepted.
    """
    filename = (model.filename or "imported.stl").strip() or "imported.stl"
    lower = filename.lower()
    if lower.endswith((".step", ".stp")):
        ext = ".step"
        template_id = "imported_step"
        scope_var = "imported_part"
    elif lower.endswith(".stl"):
        ext = ".stl"
        template_id = "imported_stl"
        scope_var = "imported_mesh"
    else:
        raise HTTPException(
            status_code=400,
            detail="Only .stl, .step, and .stp files are supported here.",
        )

    content = await model.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    from services.codegen.store import new_design_id
    design_id = new_design_id()
    persistent = settings.output_dir / "designs" / design_id
    persistent.mkdir(parents=True, exist_ok=True)
    source_dest = persistent / f"source{ext}"
    source_dest.write_bytes(content)

    seed_name, seed_script = get_template_seed(template_id)
    display_name = name or filename or seed_name

    sandbox_result = audit_then_run(
        script=seed_script,
        targets=["stl", "glb"],
        imported_files={scope_var: str(source_dest)},
    )
    if not sandbox_result.ok:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "STL seed build failed.",
                "error": sandbox_result.payload.get("error"),
                "traceback": sandbox_result.payload.get("traceback"),
            },
        )

    parameters = derive_parameters(sandbox_result.payload)
    features = derive_named_features(
        sandbox_result.payload,
        seed_script,
        created_by="import",
    )

    design = create_design(
        name=display_name,
        script=seed_script,
        parameters=parameters,
        features=features,
        process=process,
        metadata={
            "template_id": template_id,
            "imported_files": {scope_var: str(source_dest)},
            "source_filename": filename,
            "source_format": ext.lstrip("."),
        },
        design_id=design_id,
    )

    # Move artifacts from the throwaway sandbox tmp dir into the design's
    # persistent dir (same pattern as /design/create).
    from pathlib import Path
    import shutil

    relocated: dict[str, str] = {}
    for kind, src in (sandbox_result.payload.get("artifacts") or {}).items():
        src_path = Path(src)
        if not src_path.exists():
            continue
        dst_path = persistent / src_path.name
        try:
            shutil.copy2(src_path, dst_path)
            relocated[kind] = str(dst_path)
        except Exception:
            continue
    sandbox_result.payload["artifacts"] = relocated

    build = build_from_sandbox_result(design, sandbox_result, process="fdm")
    save_build(design.id, build)

    return DesignImportSTLResponse(
        design_id=design.id,
        revision_id=design.revision_id,
        name=design.name,
        script=design.script,
        parameters=[p.model_dump() for p in design.parameters],
        features=[f.model_dump() for f in design.features],
        initial_build={
            "revision_id": build.revision_id,
            "mesh_hash": build.mesh_hash,
            "bounding_box_mm": build.bounding_box_mm,
            "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
            "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
        },
    )


@app.get("/design/flagship")
def design_flagship_list() -> dict:
    """List the 5 flagship workflows.

    These are the integration test fixtures. They double as the starter cards
    on the studio empty state from Phase 2 onward.
    """
    from services.codegen.flagship import list_flagships

    return {"flagships": list_flagships()}


class DesignFlagshipForkRequest(BaseModel):
    flagship_id: str
    name: str | None = None


@app.post("/design/flagship/fork", response_model=DesignCreateResponse)
def design_flagship_fork(request: DesignFlagshipForkRequest) -> DesignCreateResponse:
    """Fork a flagship into a new editable design — same shape as /design/create."""
    from services.codegen.flagship import get_flagship

    try:
        spec = get_flagship(request.flagship_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    script = spec["script"]
    name = request.name or spec["name"]

    try:
        sandbox_result = audit_then_run(script=script, targets=["stl", "glb"])
    except DesignBuildError as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": "Flagship audit failed.", "errors": exc.audit_errors},
        ) from exc
    if not sandbox_result.ok:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Flagship build failed.",
                "error": sandbox_result.payload.get("error"),
            },
        )

    parameters = derive_parameters(sandbox_result.payload)
    features = derive_named_features(sandbox_result.payload, script, created_by="system")
    design = create_design(
        name=name,
        script=script,
        parameters=parameters,
        features=features,
        process="either",
        metadata={"flagship_id": request.flagship_id, "source": "flagship"},
    )

    from pathlib import Path
    import shutil

    persistent = settings.output_dir / "designs" / design.id
    persistent.mkdir(parents=True, exist_ok=True)
    relocated = {}
    for kind, src in (sandbox_result.payload.get("artifacts") or {}).items():
        src_path = Path(src)
        if not src_path.exists():
            continue
        dst_path = persistent / src_path.name
        try:
            shutil.copy2(src_path, dst_path)
            relocated[kind] = str(dst_path)
        except Exception:
            continue
    sandbox_result.payload["artifacts"] = relocated

    build = build_from_sandbox_result(design, sandbox_result, process="fdm")
    save_build(design.id, build)

    editable_model = design_to_editable_model(design, build)
    return DesignCreateResponse(
        design_id=design.id,
        revision_id=design.revision_id,
        name=design.name,
        template_id=request.flagship_id,
        script=design.script,
        parameters=[p.model_dump() for p in design.parameters],
        features=[f.model_dump() for f in design.features],
        initial_build={
            "revision_id": build.revision_id,
            "mesh_hash": build.mesh_hash,
            "bounding_box_mm": build.bounding_box_mm,
            "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
            "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
        },
        editable_model=editable_model.model_dump(mode="json"),
    )


@app.get("/design/templates")
def design_templates_endpoint_aliased() -> dict:
    out: list[dict] = []
    for tid in list_template_ids():
        name, _ = get_template_seed(tid)
        out.append({"template_id": tid, "name": name})
    return {"templates": out}


@app.get("/design/{design_id}")
def design_get_endpoint(design_id: str) -> dict:
    _validate_design_id(design_id)
    from services.printer_profiles import get_profile

    record = get_record(design_id)
    return {
        "design_id": record.design.id,
        "revision_id": record.design.revision_id,
        "name": record.design.name,
        "process": record.design.process,
        "script": record.design.script,
        "parameters": [p.model_dump() for p in record.design.parameters],
        "features": [f.model_dump() for f in record.design.features],
        "printer_profile_id": (
            record.design.printer_profile_id or get_profile(settings.default_printer_profile_id).id
        ),
        "latest_build": (
            {
                "revision_id": record.latest_build.revision_id,
                "mesh_hash": record.latest_build.mesh_hash,
                "bounding_box_mm": record.latest_build.bounding_box_mm,
                "artifacts": {k: a.model_dump() for k, a in record.latest_build.artifacts.items()},
                "manufacturability": (
                    record.latest_build.manufacturability.model_dump()
                    if record.latest_build.manufacturability
                    else None
                ),
                "print_estimate": (
                    record.latest_build.print_estimate.model_dump()
                    if record.latest_build.print_estimate
                    else None
                ),
                "duration_ms": record.latest_build.duration_ms,
            }
            if record.latest_build
            else None
        ),
    }


@app.get("/design")
def design_list_endpoint() -> dict:
    return {
        "designs": [
            {
                "design_id": d.id,
                "revision_id": d.revision_id,
                "name": d.name,
                "process": d.process,
                "parameter_count": len(d.parameters),
                "feature_count": len(d.features),
            }
            for d in list_designs()
        ]
    }


@app.delete("/design/{design_id}")
def design_delete_endpoint(design_id: str) -> dict:
    """Permanently delete a design — the design.json, all revisions, all
    artifacts, and the conversation. The user has to confirm in the UI; we
    don't ask twice on the backend."""
    _validate_design_id(design_id)
    import shutil

    target = settings.output_dir / "designs" / design_id
    if not target.exists():
        raise HTTPException(status_code=404, detail="Design not found.")
    try:
        shutil.rmtree(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"deleted_design_id": design_id}


@app.get("/design/templates")
def design_templates_endpoint() -> dict:
    out: list[dict] = []
    for tid in list_template_ids():
        name, _ = get_template_seed(tid)
        out.append({"template_id": tid, "name": name})
    return {"templates": out}


class DesignChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    printer_profile_id: str | None = None
    selected_feature_id: str | None = None
    selected_feature_label: str | None = None


@app.post("/design/{design_id}/chat")
async def design_chat_endpoint(design_id: str, request: DesignChatRequest):
    _validate_design_id(design_id)
    generator = stream_design_turn(
        design_id,
        request.message,
        printer_profile_id=_effective_printer_id(design_id, request.printer_profile_id),
        selected_feature_id=request.selected_feature_id,
        selected_feature_label=request.selected_feature_label,
    )
    return StreamingResponse(generator, media_type="text/event-stream")


@app.get("/design/{design_id}/conversation")
def design_conversation_endpoint(design_id: str) -> dict:
    _validate_design_id(design_id)
    return {
        "design_id": design_id,
        "messages": load_design_conversation(design_id),
    }


class DesignExportRequest(BaseModel):
    preset: str = "fdm"
    expected_revision_id: str | None = None
    printer_profile_id: str | None = None


class PrintBundleRequest(BaseModel):
    expected_revision_id: str | None = None
    printer_profile_id: str | None = None


@app.post("/design/{design_id}/export")
def design_export_endpoint(design_id: str, request: DesignExportRequest) -> dict:
    """Multi-process bundle export. Pick a goal (fdm/cnc/docs/all) → get a ZIP.

    Hides the file-format zoo behind the user's actual question — what are
    they going to do with the part?
    """
    _validate_design_id(design_id)
    from services.codegen.design_export import export_preset_bundle
    from services.codegen.store import get_design

    if request.preset not in ("fdm", "cnc", "docs", "all"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset: {request.preset}. Use one of fdm/cnc/docs/all.",
        )

    design = get_design(design_id)
    return export_preset_bundle(
        design,
        preset=request.preset,  # type: ignore[arg-type]
        expected_revision_id=request.expected_revision_id,
        printer_profile_id=_effective_printer_id(design, request.printer_profile_id),
    )


@app.post("/design/{design_id}/print-bundle")
@app.post("/design/{design_id}/make-printable")
def design_print_bundle_endpoint(design_id: str, request: PrintBundleRequest) -> dict:
    _validate_design_id(design_id)
    from services.codegen.design_export import export_preset_bundle
    from services.codegen.store import get_design

    design = get_design(design_id)
    bundle = export_preset_bundle(
        design,
        preset="fdm",
        expected_revision_id=request.expected_revision_id,
        printer_profile_id=_effective_printer_id(design, request.printer_profile_id),
    )
    manifest = bundle.get("manifest") or {}
    report = manifest.get("manufacturability") or {}
    issues = report.get("issues") or []
    estimate = manifest.get("print_estimate") or {}
    status = report.get("status") or "warn"
    remaining_issues = [
        {
            "severity": issue.get("severity"),
            "code": issue.get("code"),
            "message": issue.get("message"),
            "location": issue.get("location"),
            "suggestion": issue.get("suggestion"),
            "process": issue.get("process"),
        }
        for issue in issues
    ]
    slicer_ready = Path(settings.prusaslicer_path).exists()
    mass = estimate.get("filament_g")
    minutes = estimate.get("print_minutes")
    if status == "safe":
        summary_bits = ["Exported FDM bundle", "no manufacturability warnings"]
    else:
        labels: list[str] = []
        for issue in remaining_issues:
            code = issue.get("code")
            if code:
                labels.append(str(code))
                continue
            message = issue.get("message")
            if message:
                truncated = str(message).strip().splitlines()[0]
                labels.append(truncated[:50] + ("…" if len(truncated) > 50 else ""))
        issue_summary = ", ".join(labels) or "manufacturability checks"
        severity = "UNPRINTABLE" if status == "unprintable" else "WARN"
        summary_bits = [
            "Exported FDM bundle",
            f"still {severity}: {issue_summary}",
        ]
    if not slicer_ready:
        summary_bits.append("slicer not configured, STL/GLB only")
    if mass is not None:
        summary_bits.append(f"{float(mass):.0f}g")
    if minutes is not None:
        summary_bits.append(f"{float(minutes):.0f}min")
    return {
        **bundle,
        "status": status,
        "remaining_issues": remaining_issues,
        "slicer_ready": slicer_ready,
        "summary": " · ".join(summary_bits),
    }


@app.get("/design/{design_id}/revisions")
def design_revisions_endpoint(design_id: str) -> dict:
    """Timeline of past revisions (newest first).

    Each revision summary has the GLB url for thumbnail rendering, mesh hash,
    bounding box, manufacturability status, and build duration.
    """
    _validate_design_id(design_id)
    from services.codegen.store import list_revisions

    return {
        "design_id": design_id,
        "revisions": list_revisions(design_id),
    }


@app.get("/design/{design_id}/revisions/{revision_id}/diff")
def design_revision_diff_endpoint(design_id: str, revision_id: str) -> dict:
    _validate_design_id(design_id)
    _validate_design_id(revision_id)
    from services.codegen.diff import revision_diff

    try:
        return revision_diff(design_id, revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class DesignRevisionRestoreRequest(BaseModel):
    revision_id: str


@app.delete("/design/{design_id}/revisions/{revision_id}")
def design_revisions_delete_endpoint(design_id: str, revision_id: str) -> dict:
    """Remove a past revision's snapshot from disk. Refuses the current head."""
    _validate_design_id(design_id)
    _validate_design_id(revision_id)
    from services.codegen.store import delete_revision

    try:
        removed = delete_revision(design_id, revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Revision not found.")
    return {"design_id": design_id, "deleted_revision_id": revision_id}


@app.post("/design/{design_id}/revisions/restore")
def design_revisions_restore_endpoint(
    design_id: str, request: DesignRevisionRestoreRequest
) -> dict:
    """Roll the design back to a past revision (script + parameters + build).

    The current head becomes the parent of the restored revision — subsequent
    edits branch from here. Original revisions remain on disk untouched.
    """
    _validate_design_id(design_id)
    _validate_design_id(request.revision_id)
    from services.codegen.store import restore_revision

    try:
        build_payload = restore_revision(design_id, request.revision_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "design_id": design_id,
        "restored_revision_id": request.revision_id,
        "build": build_payload,
    }


class DesignBuildRequest(BaseModel):
    targets: list[str] = ["stl", "step", "glb"]
    process: str = "fdm"
    slice_gcode: bool = False
    printer_profile_id: str | None = None


class DesignParameterUpdate(BaseModel):
    name: str
    value: float | int | bool | str


class DesignParameterLockUpdate(BaseModel):
    name: str
    locked: bool


@app.post("/design/{design_id}/parameter")
def design_parameter_endpoint(design_id: str, request: DesignParameterUpdate) -> dict:
    """Set one parameter and rebuild — no AI, no token spend.

    This is the slider / number-input path. The same validation as
    update_parameter (sandbox-build the script with the new value to confirm
    it doesn't crash) but no Anthropic round trip. Subsecond latency for
    simple parametric designs.
    """
    _validate_design_id(design_id)
    from services.codegen.store import get_design, save_design, new_revision_id, save_build
    from services.codegen.engine import build_design

    design = get_design(design_id)
    target = next((p for p in design.parameters if p.name == request.name), None)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"No parameter named '{request.name}'.",
        )
    if target.locked:
        raise HTTPException(
            status_code=423,
            detail=f"Parameter '{request.name}' is locked.",
        )

    # Coerce string inputs (sliders / number inputs send strings) to the
    # parameter's existing runtime type — same logic as the agent's tool.
    # If a fractional value lands on an int parameter we reject the request
    # rather than silently truncating; the user's intent was probably to
    # increase precision, and a 200-OK with `value: 3` for an input of
    # `value: 3.7` is worse than a 400 explaining the type.
    existing = target.value
    requested_value = request.value
    new_value: object = requested_value
    try:
        if isinstance(existing, bool):
            new_value = (
                bool(requested_value)
                if not isinstance(requested_value, str)
                else requested_value.lower() in ("1", "true", "yes", "on")
            )
        elif isinstance(existing, int) and not isinstance(existing, bool):
            as_float = float(requested_value)
            if as_float != int(as_float):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Parameter '{request.name}' is an integer; got {requested_value!r}. "
                        f"Pass a whole number or change the parameter type."
                    ),
                )
            new_value = int(as_float)
        elif isinstance(existing, float):
            new_value = float(requested_value)
    except HTTPException:
        raise
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Bad value for '{request.name}': {exc}") from exc

    if existing == new_value:
        return {
            "ok": True,
            "noop": True,
            "design_id": design_id,
            "revision_id": design.revision_id,
            "name": request.name,
            "value": new_value,
        }

    # Mutate, persist, build, save build.
    target.value = new_value
    design.parent_revision_id = design.revision_id
    design.revision_id = new_revision_id()
    save_design(design)

    try:
        build = build_design(
            design,
            targets=["stl", "glb"],
            process="fdm",
            printer_profile_id=_effective_printer_id(design, None),
        )
    except DesignBuildError as exc:
        # Roll back the parameter change.
        target.value = existing
        design.revision_id = design.parent_revision_id or design.revision_id
        save_design(design)
        raise HTTPException(
            status_code=400,
            detail={"message": "Parameter change rejected by build.", "error": str(exc)},
        ) from exc

    save_build(design.id, build)
    return {
        "ok": True,
        "design_id": design_id,
        "revision_id": design.revision_id,
        "name": request.name,
        "value": new_value,
        "build": {
            "revision_id": build.revision_id,
            "mesh_hash": build.mesh_hash,
            "bounding_box_mm": build.bounding_box_mm,
            "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
            "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
            "duration_ms": build.duration_ms,
        },
    }


@app.post("/design/{design_id}/parameter-lock")
def design_parameter_lock_endpoint(
    design_id: str, request: DesignParameterLockUpdate
) -> dict:
    _validate_design_id(design_id)
    from services.codegen.store import get_design, save_design

    design = get_design(design_id)
    target = next((p for p in design.parameters if p.name == request.name), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"No parameter named '{request.name}'.")
    target.locked = request.locked
    save_design(design)
    return {
        "ok": True,
        "design_id": design_id,
        "revision_id": design.revision_id,
        "name": request.name,
        "locked": target.locked,
    }


class DesignPrinterUpdate(BaseModel):
    profile_id: str


@app.post("/design/{design_id}/printer")
def design_printer_endpoint(design_id: str, request: DesignPrinterUpdate) -> dict:
    """Bind the design to a specific printer profile.

    Stored on the design and immediately rebuilds the current revision so the
    manufacturability panel reflects the selected printer without waiting for
    the next slider drag or chat turn.
    """
    _validate_design_id(design_id)
    from services.codegen.store import get_design, save_build, save_design
    from services.printer_profiles import get_profile

    design = get_design(design_id)
    # Resolve through the registry so we reject unknown ids cleanly. The
    # registry falls back to the default for unknown ids; we want a hard
    # error here instead so the UI knows its dropdown is stale.
    available = {p.id for p in list_printer_profiles()}
    if request.profile_id not in available:
        raise HTTPException(
            status_code=404, detail=f"Unknown printer profile: {request.profile_id}"
        )
    profile = get_profile(request.profile_id)
    design.printer_profile_id = profile.id
    try:
        build = build_design(
            design,
            targets=["stl", "glb"],
            printer_profile_id=profile.id,
            process="fdm",
        )
    except DesignBuildError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": "Printer profile rebuild failed.", "error": str(exc)},
        ) from exc
    save_design(design)
    save_build(design.id, build)
    return {
        "ok": True,
        "design_id": design_id,
        "printer_profile_id": profile.id,
        "label": profile.label,
        "build": {
            "revision_id": build.revision_id,
            "mesh_hash": build.mesh_hash,
            "bounding_box_mm": build.bounding_box_mm,
            "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
            "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
        },
    }


def _effective_printer_id(
    design_or_id: str | None,
    request_profile_id: str | None,
) -> str | None:
    """Pick the printer id for a request: explicit override → design pref → default.

    ``design_or_id`` may be a Design instance (preferred — already loaded) or a
    design_id (we'll fetch it). Returns ``None`` only when the design is
    missing and no override is provided, in which case the engine falls back
    to its own default.
    """
    if request_profile_id:
        return request_profile_id
    from services.codegen.store import get_design_or_none
    from services.codegen.models import Design as _Design

    design = (
        design_or_id
        if isinstance(design_or_id, _Design)
        else get_design_or_none(design_or_id) if design_or_id else None
    )
    if design and design.printer_profile_id:
        return design.printer_profile_id
    return None


@app.post("/design/{design_id}/build")
def design_build_endpoint(design_id: str, request: DesignBuildRequest) -> dict:
    _validate_design_id(design_id)
    design = get_design(design_id)
    try:
        build = build_design(
            design,
            targets=request.targets,
            printer_profile_id=_effective_printer_id(design, request.printer_profile_id),
            process=request.process,
        )
    except DesignBuildError as exc:
        raise HTTPException(
            status_code=400,
            detail={"message": "Build failed.", "error": str(exc), "audit_errors": exc.audit_errors},
        ) from exc

    if request.slice_gcode and request.process == "fdm" and "stl" in build.artifacts:
        from pathlib import Path

        from services.codegen.estimate import parse_gcode_estimate
        from slicer_service import _slice_mesh

        stl_path = Path(build.artifacts["stl"].path)
        gcode_path = stl_path.parent / "model.gcode"
        if _slice_mesh(
            stl_path,
            gcode_path,
            profile_id=_effective_printer_id(design, request.printer_profile_id),
        ):
            from services.codegen.models import BuildArtifact

            build.artifacts["gcode"] = BuildArtifact(
                kind="gcode",
                url=f"/artifacts/designs/{design.id}/{gcode_path.name}",
                path=str(gcode_path),
                bytes=gcode_path.stat().st_size,
            )
            estimate = parse_gcode_estimate(gcode_path)
            if estimate is not None:
                build.print_estimate = estimate

    save_build(design_id, build)
    return {
        "design_id": design_id,
        "revision_id": build.revision_id,
        "mesh_hash": build.mesh_hash,
        "bounding_box_mm": build.bounding_box_mm,
        "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
        "manufacturability": build.manufacturability.model_dump() if build.manufacturability else None,
        "print_estimate": build.print_estimate.model_dump() if build.print_estimate else None,
        "duration_ms": build.duration_ms,
    }
