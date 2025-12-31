from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from services.deepgram_stt import transcribe_audio
from services.gemini_intent import extract_prompt, extract_prompt_from_image
from services.generation import GenerationResult, generate_model, generate_model_from_image
from services.library import resolve_library_item, search_library
from slicer_service import ProcessResult, process_model
from services.job_store import ensure_job, record_error, update_job, upload_artifact

app = FastAPI(title="Voice-to-3D-Print Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

artifacts_path = Path(settings.output_dir)
artifacts_path.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=artifacts_path), name="artifacts")


def _compact_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value is not None}


class GenerateRequest(BaseModel):
    prompt: str
    provider: str | None = None
    job_id: str | None = None
    input_type: str | None = None
    prompt_raw: str | None = None


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


class ProcessResponse(BaseModel):
    job_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None


class IntentRequest(BaseModel):
    transcript: str
    job_id: str | None = None
    input_type: str | None = None


class IntentResponse(BaseModel):
    job_id: str
    prompt: str


class ImageIntentResponse(BaseModel):
    job_id: str
    prompt: str


class STTResponse(BaseModel):
    transcript: str


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "sketchfab_enabled": bool(settings.sketchfab_api_token),
    }


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest) -> GenerateResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload({
            "status": "generating",
            "provider": (request.provider or settings.threed_provider).lower(),
            "input.type": request.input_type,
            "input.prompt_raw": request.prompt_raw,
            "input.prompt_final": request.prompt,
        }),
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
    return GenerateResponse(
        job_id=job_id,
        provider=result.provider,
        task_id=result.task_id,
        glb_url=result.glb_url,
    )


@app.post("/generate-image", response_model=GenerateResponse)
async def generate_image(
    provider: str | None = None,
    job_id: str | None = Form(None),
    input_type: str | None = Form(None),
    image: UploadFile = File(...),
) -> GenerateResponse:
    job_id = job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload({
            "status": "generating",
            "provider": (provider or settings.threed_provider).lower(),
            "input.type": input_type or "image",
            "input.image_name": image.filename,
            "input.image_content_type": image.content_type,
        }),
    )
    try:
        content = await image.read()
        update_job(
            job_id,
            {
                "input.image_size": len(content),
            },
        )
        result: GenerationResult = await generate_model_from_image(
            content,
            image.filename or "upload.jpg",
            image.content_type or "image/jpeg",
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
    return GenerateResponse(
        job_id=job_id,
        provider=result.provider,
        task_id=result.task_id,
        glb_url=result.glb_url,
    )


@app.post("/process-model", response_model=ProcessResponse)
def process(request: ProcessRequest) -> ProcessResponse:
    job_id = request.job_id or uuid.uuid4().hex
    ensure_job(
        job_id,
        _compact_payload({
            "status": "slicing",
            "provider": request.provider,
            "input.type": request.input_type,
            "input.prompt_final": request.prompt,
            "input.library_id": request.library_id,
            "input.library_source": request.library_source,
            "input.library_title": request.library_title,
        }),
    )
    try:
        result: ProcessResult = process_model(request.glb_url, job_id=job_id)
    except Exception as exc:
        record_error(job_id, "process-model", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    glb_upload = upload_artifact(job_id, result.glb_path)
    stl_upload = upload_artifact(job_id, result.stl_path)
    gcode_upload = upload_artifact(job_id, result.gcode_path) if result.gcode_path else None

    job_prefix = f"/artifacts/{result.job_id}"
    glb_url = glb_upload["url"] if glb_upload else f"{job_prefix}/{result.glb_path.name}"
    stl_url = stl_upload["url"] if stl_upload else f"{job_prefix}/{result.stl_path.name}"
    gcode_url = (
        gcode_upload["url"] if gcode_upload else
        (f"{job_prefix}/{result.gcode_path.name}" if result.gcode_path is not None else None)
    )

    update_job(
        job_id,
        {
            "status": "ready",
            "artifacts.glb_url": glb_url,
            "artifacts.stl_url": stl_url,
            "artifacts.gcode_url": gcode_url,
            "artifacts.glb_size": glb_upload["size"] if glb_upload else result.glb_path.stat().st_size,
            "artifacts.stl_size": stl_upload["size"] if stl_upload else result.stl_path.stat().st_size,
            "artifacts.gcode_size": gcode_upload["size"] if gcode_upload else (
                result.gcode_path.stat().st_size if result.gcode_path else None
            ),
        },
    )
    return ProcessResponse(
        job_id=result.job_id,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
    )


@app.post("/intent", response_model=IntentResponse)
async def intent(request: IntentRequest) -> IntentResponse:
    job_id = request.job_id or uuid.uuid4().hex
    prompt = await extract_prompt(request.transcript)
    if not prompt:
        record_error(job_id, "intent", "Failed to extract prompt.")
        raise HTTPException(status_code=500, detail="Failed to extract prompt.")
    ensure_job(
        job_id,
        _compact_payload({
            "status": "intent_ready",
            "input.type": request.input_type,
            "input.transcript": request.transcript,
            "input.prompt_final": prompt,
        }),
    )
    return IntentResponse(job_id=job_id, prompt=prompt)


@app.post("/image-intent", response_model=ImageIntentResponse)
async def image_intent(
    image: UploadFile = File(...),
    job_id: str | None = Form(None),
    input_type: str | None = Form(None),
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
            }
        ),
    )
    try:
        content = await image.read()
        update_job(
            job_id,
            {
                "input.image_size": len(content),
            },
        )
        prompt = await extract_prompt_from_image(
            content,
            image.content_type or "image/jpeg",
        )
    except Exception as exc:
        record_error(job_id, "image-intent", str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not prompt:
        record_error(job_id, "image-intent", "Failed to extract prompt.")
        raise HTTPException(status_code=500, detail="Failed to extract prompt.")

    update_job(
        job_id,
        {
            "status": "intent_ready",
            "input.prompt_final": prompt,
        },
    )

    return ImageIntentResponse(job_id=job_id, prompt=prompt)


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
