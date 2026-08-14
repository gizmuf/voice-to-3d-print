# Linux / VPS runbook

Canonical checkout:

```text
/home/codex/workspace/repos/candao-3d-stack
```

The VPS checkout is the development and validation environment. Production
traffic remains on Cloud Run until a separately approved migration changes DNS
and routing.

## Verified host baseline

- Ubuntu 24.04, x86_64
- Python 3.12
- Node.js 22
- 8 vCPU, 23 GiB RAM
- PrusaSlicer 2.7.2

## Backend

```bash
cd /home/codex/workspace/repos/candao-3d-stack/backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
PULSAI_AUTH_REQUIRED=false \
PULSAI_INSECURE_LOCAL_DEV=true \
PULSAI_PUBLIC_SAFE_MODE=true \
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Verify `/health`, then create a template design, change one parameter, confirm
that revision and mesh hashes changed, and fetch the new GLB. Slicing readiness
is not proven until a safe model produces a G-code artifact.

## Frontend

`NEXT_PUBLIC_*` values are embedded at build time:

```bash
cd /home/codex/workspace/repos/candao-3d-stack/frontend
npm ci
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000 \
NEXT_PUBLIC_STT_URL=http://127.0.0.1:8010 \
npm run build
npm start -- --hostname 127.0.0.1 --port 3000
```

For public VPS routing, replace the URLs with approved HTTPS routes before the
build. Do not expose raw backend/STT ports directly to the internet.

## STT

```bash
cd /home/codex/workspace/repos/candao-3d-stack/stt-service
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PULSAI_ALLOW_PLATFORM_AI_SPEND=false \
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8010
```

`/health` works without Deepgram. Real transcription remains unavailable until
an approved `DEEPGRAM_API_KEY_FILE` or Cloud Run Secret Manager reference is
configured and a microphone test passes.

## Free validation gate

```bash
cd /home/codex/workspace/repos/candao-3d-stack/backend
PULSAI_AUTH_REQUIRED=false PULSAI_INSECURE_LOCAL_DEV=true \
PULSAI_PUBLIC_SAFE_MODE=true \
.venv/bin/python -m pytest -q tests \
  --ignore=tests/ai/evals/test_eval_runner.py \
  --ignore=tests/ai/evals_v2/test_eval_runner_v2.py

cd /home/codex/workspace/repos/candao-3d-stack/frontend
npm run test:unit
npx --no-install tsc --noEmit
npm run build

# Starts the frontend automatically; start the backend on 127.0.0.1:8000 first.
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000 \
NEXT_PUBLIC_STT_URL=http://127.0.0.1:8010 \
PLAYWRIGHT_BACKEND_URL=http://127.0.0.1:8000 \
npx --no-install playwright test tests/e2e/cad-to-print-free.spec.ts
```

Never run live Anthropic/Meshy/Tripo evals without an explicit budget.

The free E2E proves one known-safe parametric FDM flow: browser creation,
zero-cost parameter edit, changed revision/mesh hash/GLB, manufacturability
gate, PrusaSlicer G-code, and downloadable ZIP. It does not prove arbitrary
parts, image interpretation, microphone STT, imported CAD, every browser or
printer, structural safety, or a physical print.

The default local and production-safe posture is:

```text
PULSAI_ALLOW_PLATFORM_AI_SPEND=false
PULSAI_ALLOW_PUBLIC_ARTIFACTS=false
PULSAI_AUTH_REQUIRED=true
PULSAI_PUBLIC_SAFE_MODE=true
PULSAI_ALLOW_UNTRUSTED_CAD_CODE=false
```

With these defaults, deterministic CAD/build/slicing remains available, while
paid providers require customer BYOK or a separately approved platform-spend
change. Do not enable public artifacts as a substitute for authentication.

## Backup and restore

Use [BACKUP_RESTORE.md](BACKUP_RESTORE.md). A release or data migration is not
production-ready until an isolated Firestore/GCS restore drill has passed.
