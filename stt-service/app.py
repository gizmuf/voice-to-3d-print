from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


def _secret_env(name: str) -> str:
    secret_file = os.getenv(f"{name}_FILE", "").strip()
    if secret_file:
        try:
            return Path(secret_file).read_text().strip()
        except OSError as exc:
            raise RuntimeError(f"Configured secret file for {name} is unreadable.") from exc
    return os.getenv(name, "")


DEEPGRAM_API_KEY = _secret_env("DEEPGRAM_API_KEY")
STT_INTERNAL_TOKEN = _secret_env("PULSAI_STT_INTERNAL_TOKEN")
DEEPGRAM_BASE_URL = os.getenv("DEEPGRAM_BASE_URL", "https://api.deepgram.com").rstrip("/")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
ALLOW_PLATFORM_AI_SPEND = os.getenv("PULSAI_ALLOW_PLATFORM_AI_SPEND", "").strip().lower() in {
    "1", "true", "yes", "on"
}
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_STT_REQUEST_BYTES = MAX_AUDIO_BYTES + 1024 * 1024
SUPPORTED_LANGUAGES = {"pl", "en", "multi"}
CAD_VOCABULARY = [
    "Pulsai",
    "CAD",
    "STL",
    "STEP",
    "GLB",
    "druk 3D",
    "średnica",
    "promień",
    "wysokość",
    "głębokość",
    "otwór",
    "fazowanie",
    "zaokrąglenie",
    "kołowrotek",
    "bieżnia",
    "szczebelki",
    "szprychy",
    "chomik",
    "oś",
    "łożysko",
]

app = FastAPI(title="Pulsai STT")
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _has_valid_internal_token(request: Request) -> bool:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return bool(
        STT_INTERNAL_TOKEN
        and scheme.lower() == "bearer"
        and token
        and secrets.compare_digest(token, STT_INTERNAL_TOKEN)
    )


@app.middleware("http")
async def authenticate_before_multipart_parsing(request: Request, call_next):
    """Reject unauthenticated/oversized STT bodies before FastAPI parses them."""
    if request.url.path == "/stt" and request.method != "OPTIONS":
        if not _has_valid_internal_token(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "STT service authentication required."},
            )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_bytes = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length."},
                )
            if request_bytes < 0 or request_bytes > MAX_STT_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Audio file is too large."},
                )
    return await call_next(request)


def request_params(language: str) -> list[tuple[str, str]]:
    selected_language = language if language in SUPPORTED_LANGUAGES else "pl"
    params = [
        ("model", DEEPGRAM_MODEL),
        ("language", selected_language),
        ("punctuate", "true"),
        ("smart_format", "true"),
        ("numerals", "true"),
    ]
    params.extend(("keyterm", term) for term in CAD_VOCABULARY)
    if selected_language == "en":
        params.append(("measurements", "true"))
    return params


def extract_transcript(payload: dict[str, Any]) -> str | None:
    try:
        transcript = payload["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError, TypeError):
        return None
    return transcript.strip() if isinstance(transcript, str) and transcript.strip() else None


@app.get("/health")
async def health() -> dict[str, bool]:
    return {
        "ok": True,
        "provider_ready": bool(ALLOW_PLATFORM_AI_SPEND and DEEPGRAM_API_KEY),
        "platform_ai_spend_enabled": ALLOW_PLATFORM_AI_SPEND,
    }


@app.post("/stt")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form("pl"),
) -> dict[str, str]:
    if not _has_valid_internal_token(request):
        raise HTTPException(status_code=401, detail="STT service authentication required.")
    if not ALLOW_PLATFORM_AI_SPEND:
        raise HTTPException(
            status_code=403,
            detail="Platform-paid transcription is disabled; use browser speech recognition.",
        )
    if not DEEPGRAM_API_KEY:
        raise HTTPException(status_code=503, detail="STT is not configured.")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await audio.read(min(1024 * 1024, MAX_AUDIO_BYTES - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio file is too large.")
        chunks.append(chunk)
    content = b"".join(chunks)
    if not content:
        raise HTTPException(status_code=400, detail="Nagranie jest puste.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Nagranie jest za duże.")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = await client.post(
                f"{DEEPGRAM_BASE_URL}/v1/listen",
                params=request_params(language),
                content=content,
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": audio.content_type or "application/octet-stream",
                },
            )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="Transkrypcja chwilowo nie działa.") from error

    transcript = extract_transcript(response.json())
    if not transcript:
        raise HTTPException(status_code=422, detail="Nie usłyszałem wyraźnej komendy.")
    return {"transcript": transcript}
