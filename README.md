# 3dprint (Serverless Prototype)

A voice-driven pipeline that captures speech, extracts 3D design intent, generates a GLB model from a cloud API, repairs geometry with MeshLib, and slices to G-code with PrusaSlicer. The default providers favor lower-cost options for prototyping.

## Stack
- **Frontend:** Next.js + React + browser SpeechRecognition + `<model-viewer>`
- **Voice Orchestration:** Browser STT (default) or Deepgram STT + Gemini intent extraction via proxy
- **3D Generation:** Meshy (default), Tripo, Parametric (free), Trellis2 (image-to-3D via GPU service), TripoSR (local image-to-3D)
- **Manufacturing:** MeshLib repair + PrusaSlicer CLI

## Architecture Flow
1. User speaks in browser (Web Speech API or Deepgram recording).
2. Speech is transcribed locally (browser) or via Deepgram.
3. Gemini extracts a clean text prompt.
4. Selected provider generates a GLB model from the prompt or image.
5. MeshLib repairs mesh and exports STL.
6. PrusaSlicer produces G-code for download.

## Local Setup (Mac)
### 1) Backend
Python 3.10–3.13 recommended (Pipecat does not yet support 3.14).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set env vars (copy from `backend/.env.example`):
```bash
cp .env.example .env
```

Run FastAPI:
```bash
uvicorn app:app --reload --port 8000
```

### 2) Frontend
```bash
cd ../frontend
npm install
npm run dev
```

Open http://localhost:3000

## Notes
- **Cheapest defaults:** `THREED_PROVIDER=parametric` and Gemini via the existing proxy (`GEMINI_PROXY_URL`).
- **PrusaSlicer:** Set `PRUSASLICER_PATH` and `PRUSASLICER_CONFIG` in `.env`.
- **Provider switching:** Set `THREED_PROVIDER=meshy`, `THREED_PROVIDER=tripo`, `THREED_PROVIDER=parametric`, `THREED_PROVIDER=trellis2`, or `THREED_PROVIDER=triposr`.
- **Gemini proxy:** The default proxy is the Gut Feeling Cloud Run endpoint already wired with a Gemini key.
- **Deepgram STT (optional):** Set `DEEPGRAM_API_KEY` to enable server transcription from recorded audio.
- **Model library option:** Add GLB links to `backend/data/model_library.json` for local catalog search.
- **Sketchfab search (optional):** Set `SKETCHFAB_API_TOKEN` to search downloadable models and retrieve GLB links.
- **Image to model:** `/generate-image` supports Meshy, Tripo, Trellis2, and TripoSR (set `provider` query param).
- **Trellis2 API:** Set `TRELLIS2_API_URL` plus `TRELLIS2_IMAGE_ENDPOINT` to enable image-to-3D via a Trellis2 GPU service. Text-to-3D requires a custom `TRELLIS2_TEXT_ENDPOINT`.
- **TripoSR local:** Set `TRIPOSR_ROOT` (path to the TripoSR repo) and optionally `TRIPOSR_CACHE_DIR` (e.g. an external drive). TripoSR is image-to-3D only and runs on CPU if no CUDA GPU is present.

## Local TripoSR (Optional)
1) Clone TripoSR somewhere with space (external drive recommended).
2) Create a TripoSR venv and install its dependencies.
3) Set in `backend/.env`:
   - `TRIPOSR_ROOT=/Volumes/Gizmuf external/3dprint/triposr/TripoSR`
   - `TRIPOSR_CACHE_DIR=/Volumes/Gizmuf external/3dprint/triposr/cache`
   - `TRIPOSR_PYTHON=/Volumes/Gizmuf external/3dprint/triposr/venv/bin/python`
   - Optional: `OUTPUT_DIR=/Volumes/Gizmuf external/3dprint/artifacts` to keep artifacts off the Mac disk
   - Note: wrap paths with spaces in quotes in your shell/env files.

## Endpoints
- `POST /generate` → calls the selected provider and returns `glb_url`
- `POST /process-model` → downloads GLB, repairs, slices, returns artifact URLs
- `POST /generate-image?provider=meshy|tripo|trellis2|triposr` → image-to-3D task
- `GET /artifacts/{job_id}/output.gcode` → G-code download

## Repo Structure
```
backend/
  app.py
  config.py
  requirements.txt
  services/
    generation.py
    gemini_intent.py
    library.py
  slicer_service.py
frontend/
  app/
  components/
  styles/
```
