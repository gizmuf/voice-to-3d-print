# Voice-to-3D-Print (Serverless Prototype)

A voice-driven pipeline that captures speech, extracts 3D design intent, generates a GLB model from a cloud API, repairs geometry with MeshLib, and slices to G-code with PrusaSlicer. The default providers favor lower-cost options for prototyping.

## Stack
- **Frontend:** Next.js + React + Pipecat JS client + `<model-viewer>`
- **Voice Orchestration:** Pipecat (WebRTC, Deepgram STT, Gemini intent extraction via proxy)
- **3D Generation:** Meshy (default) with Tripo as an optional provider
- **Manufacturing:** MeshLib repair + PrusaSlicer CLI

## Architecture Flow
1. User speaks in browser (Pipecat WebRTC).
2. Deepgram transcribes speech in real time.
3. GPT-4o-mini extracts a clean text prompt.
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

Run Pipecat bot (WebRTC transport):
```bash
python bot.py -t webrtc --port 7860
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
- **Pipecat JS SDK:** The frontend assumes `@pipecat-ai/client`. Adjust `frontend/types/pipecat.d.ts` and the client usage if your SDK package name differs.

## Endpoints
- `POST /generate` → calls Meshy/Tripo and returns `glb_url`
- `POST /process-model` → downloads GLB, repairs, slices, returns artifact URLs
- `GET /artifacts/{job_id}/output.gcode` → G-code download

## Repo Structure
```
backend/
  app.py
  bot.py
  config.py
  requirements.txt
  services/
    generation.py
  slicer_service.py
frontend/
  app/
  components/
  styles/
```
