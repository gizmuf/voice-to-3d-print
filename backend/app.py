from __future__ import annotations

import json
import uuid
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import settings
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
from services.useful_objects import (
    build_useful_object,
    build_useful_structured_spec,
    preview_useful_object,
    route_mode,
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
        "cad_ready": True,
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
        structured_spec = build_useful_structured_spec(
            request.raw_text,
            source=request.source,
            existing_spec=request.existing_spec,
        )
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
        preview = preview_useful_object(request.structured_spec, job_id=job_id)
    except Exception as exc:
        record_error(job_id, "preview-useful", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, preview.glb_path)
    glb_url = _artifact_url(glb_upload, preview.glb_path, job_id)
    update_job(
        job_id,
        {
            "status": "preview_ready",
            "preview_artifacts.glb_url": glb_url,
            "preview_artifacts.glb_size": glb_upload["size"] if glb_upload else preview.glb_path.stat().st_size,
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
        preview_id=job_id,
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
        build = build_useful_object(request.structured_spec, job_id=job_id)
        validation = validate_mesh_file(build.stl_path)
        gcode_generated = _slice_mesh(build.stl_path, build.stl_path.parent / "output.gcode")
        validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
        gcode_path = build.stl_path.parent / "output.gcode" if gcode_generated else None
    except Exception as exc:
        record_error(job_id, "build-useful", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, build.glb_path)
    stl_upload = upload_artifact(job_id, build.stl_path)
    gcode_upload = upload_artifact(job_id, gcode_path) if gcode_path else None
    glb_url = _artifact_url(glb_upload, build.glb_path, job_id)
    stl_url = _artifact_url(stl_upload, build.stl_path, job_id)
    gcode_url = _artifact_url(gcode_upload, gcode_path, job_id) if gcode_path else None

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

    update_job(
        job_id,
        {
            "status": "ready" if validation.get("validation_status") != "failed" else "needs_review",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "artifacts.gcode_url": gcode_url,
            "validation": validation,
            "preview_artifacts.glb_url": f"/artifacts/{job_id}/preview.glb"
            if (build.glb_path.parent / "preview.glb").exists()
            else None,
        },
    )
    if request.project_id:
        update_project(request.project_id, {"current_job_id": job_id})

    bundle_response = bundle(job_id)
    bundle_url = bundle_response.get("url")
    return UsefulBuildResponse(
        job_id=job_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        validation=validation,
        bundle_url=bundle_url,
        structured_spec=request.structured_spec,
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
