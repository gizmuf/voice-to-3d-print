from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from services.deepgram_stt import transcribe_audio
from services.gemini_intent import extract_prompt
from services.generation import GenerationResult, generate_model
from services.library import resolve_library_item, search_library
from slicer_service import ProcessResult, process_model

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


class GenerateRequest(BaseModel):
    prompt: str
    provider: str | None = None


class GenerateResponse(BaseModel):
    provider: str
    task_id: str
    glb_url: str


class ProcessRequest(BaseModel):
    glb_url: str


class ProcessResponse(BaseModel):
    job_id: str
    glb_url: str
    stl_url: str
    gcode_url: str | None


class IntentRequest(BaseModel):
    transcript: str


class IntentResponse(BaseModel):
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
    try:
        result: GenerationResult = await generate_model(request.prompt, provider=request.provider)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return GenerateResponse(
        provider=result.provider,
        task_id=result.task_id,
        glb_url=result.glb_url,
    )


@app.post("/process-model", response_model=ProcessResponse)
def process(request: ProcessRequest) -> ProcessResponse:
    try:
        result: ProcessResult = process_model(request.glb_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    job_prefix = f"/artifacts/{result.job_id}"
    return ProcessResponse(
        job_id=result.job_id,
        glb_url=f"{job_prefix}/{result.glb_path.name}",
        stl_url=f"{job_prefix}/{result.stl_path.name}",
        gcode_url=(
            f"{job_prefix}/{result.gcode_path.name}"
            if result.gcode_path is not None
            else None
        ),
    )


@app.post("/intent", response_model=IntentResponse)
async def intent(request: IntentRequest) -> IntentResponse:
    prompt = await extract_prompt(request.transcript)
    if not prompt:
        raise HTTPException(status_code=500, detail="Failed to extract prompt.")
    return IntentResponse(prompt=prompt)


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
