from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
    record = get_workspace(workspace_id)
    return WorkspaceResponse(
        workspace_id=record.workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        latest_preview=record.latest_preview.model_dump(mode="json") if record.latest_preview else None,
        latest_build=record.latest_build.model_dump(mode="json") if record.latest_build else None,
    )


@app.post("/workspace/{workspace_id}/mutate", response_model=WorkspaceResponse)
def mutate_workspace_endpoint(workspace_id: str, request: WorkspaceMutation) -> WorkspaceResponse:
    record = update_workspace(workspace_id, request)
    return WorkspaceResponse(
        workspace_id=record.workspace_id,
        editable_model=record.editable_model.model_dump(mode="json"),
        latest_preview=record.latest_preview.model_dump(mode="json") if record.latest_preview else None,
        latest_build=record.latest_build.model_dump(mode="json") if record.latest_build else None,
    )


@app.post("/workspace/{workspace_id}/preview", response_model=WorkspacePreviewResponse)
def preview_workspace_endpoint(workspace_id: str, request: WorkspacePreviewRequest) -> WorkspacePreviewResponse:
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
