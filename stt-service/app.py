from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware


DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_BASE_URL = os.getenv("DEEPGRAM_BASE_URL", "https://api.deepgram.com").rstrip("/")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
MAX_AUDIO_BYTES = 15 * 1024 * 1024
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


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
    return {"ok": True}


@app.post("/stt")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("pl"),
) -> dict[str, str]:
    if not DEEPGRAM_API_KEY:
        raise HTTPException(status_code=503, detail="STT is not configured.")
    content = await audio.read()
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
