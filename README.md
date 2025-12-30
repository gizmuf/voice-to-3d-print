# Voice-to-3D-Print (Serverless Prototype)

A voice-driven pipeline that captures speech, extracts 3D design intent, generates a GLB model from a cloud API, repairs geometry with MeshLib, and slices to G-code with PrusaSlicer. The default providers favor lower-cost options for prototyping.

## Stack
- **Frontend:** Next.js + React + browser SpeechRecognition + `<model-viewer>`
- **Voice Orchestration:** Browser STT (default) or Deepgram STT + Gemini intent extraction via proxy
- **3D Generation:** Meshy (default) with Tripo as an optional provider
- **Manufacturing:** MeshLib repair + PrusaSlicer CLI

## Architecture Flow
1. User speaks in browser (Web Speech API or Deepgram recording).
2. Speech is transcribed locally (browser) or via Deepgram.
3. Gemini extracts a clean text prompt.
4. Meshy generates a GLB model from the prompt.
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

Set env vars (copy from `.env.example`):
```bash
cp ../.env.example .env
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
- **Cheapest defaults:** `THREED_PROVIDER=meshy` and Gemini via the existing proxy (`GEMINI_PROXY_URL`).
- **PrusaSlicer:** Set `PRUSASLICER_PATH` and `PRUSASLICER_CONFIG` in `.env`.
- **Provider switching:** Set `THREED_PROVIDER=tripo` and `TRIPO_API_KEY` to swap generators.
- **Gemini proxy:** The default proxy is the Gut Feeling Cloud Run endpoint already wired with a Gemini key.
- **Deepgram STT (optional):** Set `DEEPGRAM_API_KEY` to enable server transcription from recorded audio.
- **Model library option:** Add GLB links to `backend/data/model_library.json` for local catalog search.
- **Sketchfab search (optional):** Set `SKETCHFAB_API_TOKEN` to search downloadable models and retrieve GLB links.

## Endpoints
- `POST /generate` → calls Meshy/Tripo and returns `glb_url`
- `POST /process-model` → downloads GLB, repairs, slices, returns artifact URLs
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
