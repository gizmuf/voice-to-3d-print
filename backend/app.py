from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from services.generation import GenerationResult, generate_model
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
    gcode_url: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


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
        gcode_url=f"{job_prefix}/{result.gcode_path.name}",
    )
