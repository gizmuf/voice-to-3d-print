# Pulsai 3D Stack

[![License: AGPL v3 or later](https://img.shields.io/badge/License-AGPL_v3_or_later-blue.svg)](LICENSE)

Pulsai 3D is an AI-first, CAD-first design studio: describe or show a part,
inspect the editable model, refine it through chat, voice, parameters, or
selection, then validate and prepare it for manufacturing. The source of truth
is build123d/OpenCascade CAD and its revisions; GLB/STL are derived artifacts.

## Stack
- **Frontend:** Next.js, React, Three.js / React Three Fiber, and drei.
- **CAD:** build123d/OpenCascade and CadQuery, with audited Python source,
  parameter snapshots, named features, revisions, and STEP-first exports.
- **AI:** deterministic local edits first; Anthropic agent for ambiguous or
  structural CAD work. Customer BYOK is supported and platform-paid AI is
  disabled by default.
- **Mesh / manufacturing:** trimesh, MeshLib, manifold3d, and PrusaSlicer CLI.
- **Voice:** browser speech recognition or the optional Deepgram STT service.
- **Persistence:** Firestore metadata and immutable GCS artifacts in managed
  production; local filesystem is only a development cache.

## Architecture Flow
1. The user starts with text, voice, an image reference, or imported CAD/mesh.
2. Deterministic parameter edits run locally; harder requests use the CAD agent
   only when the customer supplies a key or platform spend is explicitly enabled.
3. Audited CAD source builds in an isolated, resource-limited subprocess.
4. A successful revision persists source, parameters, mesh hash, STEP/STL/GLB,
   and the current preview atomically.
5. Manufacturability checks gate slicing; PrusaSlicer produces FDM G-code for
   models that pass the configured profile's hard checks.

## Local Setup

The canonical Linux/VPS instructions are in
[`docs/RUNBOOK_LINUX.md`](docs/RUNBOOK_LINUX.md).

### 1) Backend
Python 3.11–3.13 is supported by the current pinned environment.

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
- **Cheapest defaults:** `THREED_PROVIDER=parametric` and deterministic parameter edits; both avoid paid model calls.
- **PrusaSlicer:** Set `PRUSASLICER_PATH` and `PRUSASLICER_CONFIG` in `.env`.
- **Provider switching:** Set `THREED_PROVIDER=meshy`, `THREED_PROVIDER=tripo`, `THREED_PROVIDER=parametric`, `THREED_PROVIDER=trellis2`, or `THREED_PROVIDER=triposr`.
- **Legacy Gemini proxy:** There is no default. If enabled for compatibility,
  it must be owned by this stack and remains subject to the platform-spend gate.
- **Deepgram STT (optional):** Set `DEEPGRAM_API_KEY` to enable server transcription from recorded audio.
- **Model library option:** Add GLB links to `backend/data/model_library.json` for local catalog search.
- **Sketchfab search (optional):** Set `SKETCHFAB_API_TOKEN` to search downloadable models and retrieve GLB links.
- **Onshape import (optional):** Set `ONSHAPE_ACCESS_KEY` + `ONSHAPE_SECRET_KEY` for server-side STEP import from pasted Onshape Part Studio / Assembly URLs. OAuth config is scaffolded for the public multi-user version.
- **Image to model:** `/generate-image` supports Meshy, Tripo, Trellis2, and TripoSR (set `provider` query param).
- **Trellis2 API:** Set `TRELLIS2_API_URL` plus `TRELLIS2_IMAGE_ENDPOINT` to enable image-to-3D via a Trellis2 GPU service. Text-to-3D requires a custom `TRELLIS2_TEXT_ENDPOINT`.
- **TripoSR local:** Set `TRIPOSR_ROOT` (path to the TripoSR repo) and optionally `TRIPOSR_CACHE_DIR` (e.g. an external drive). TripoSR is image-to-3D only and runs on CPU if no CUDA GPU is present.

## Local TripoSR (Optional GPU Worker)

TripoSR is disabled in the baseline and is not required for CAD, preview, or
slicing. If a dedicated GPU worker is approved later, clone it outside this
checkout, create an isolated environment, and configure `TRIPOSR_ROOT`,
`TRIPOSR_CACHE_DIR`, and `TRIPOSR_PYTHON` with VPS/worker-local paths. Do not
make a laptop checkout or an unrelated product repository a runtime dependency.

## Endpoints

**Code-driven CAD engine (powerful path):**
- `GET /design/templates` → list seed scripts
- `POST /design/create` → create a new design from `prompt` / `template_id` / `script` (audits + sandbox-builds an initial STL+GLB)
- `GET /design/{id}` → get the design (script, parameters, named features, latest build)
- `GET /design` → list saved designs
- `POST /design/{id}/chat` → SSE chat with Pulsai (powerful tool set, no capability matrix)
- `GET /design/{id}/conversation` → persisted chat history
- `POST /design/{id}/build` → re-run with optional STL/STEP/DXF/GLB targets, optional G-code slice

**Legacy template path (kept for compat, scheduled for removal):**
- `POST /generate`, `POST /process-model`, `POST /generate-image?provider=…` → legacy generation
- `POST /workspace/{id}/chat` (legacy capability-matrix agent), `GET /workspace/{id}/conversation`,
  `GET /workspace/{id}/editability`, `POST /workspace/{id}/export-bundle`,
  `GET /workspace/{id}/export-bundle/dry-run` — narrowed to numeric param tweaks on fixed templates.

**Common:**
- `GET /artifacts/...` → static artifact serving
- `GET /printer-profiles` → list available printer profiles
- `GET /integrations/onshape/status` → check Onshape config
- `POST /integrations/onshape/import-step` → export STEP from an Onshape Part Studio / Assembly URL and import it as a Pulsai design

## The Pulsai Design Studio (powerful)

Frontend route: **`/design`** (open `http://localhost:3000/design`).

Each "design" *is* a [build123d](https://github.com/gumyr/build123d) Python
script. Parameters are declared via the runner-provided `pulsai.param()`
helper; named feature blocks delimited by `# @feature: name` ... `# @end`
are independently editable by the agent. The script is the source of truth;
the inspector (parameters / features / manufacturability) is a derived view.

### Chat tools (no capability matrix, no per-template gating)

| Tool | Purpose |
| --- | --- |
| `read_design` | Return current script, parameters, features, and last-build summary. |
| `query_library` | Search the snippet library (holes, polygons, patterns, fillets, shells, …). |
| `update_parameter` | Fast path for numeric tweaks — re-run the script with one override. |
| `replace_feature` | Surgically swap the body of a `# @feature: name` block. |
| `append_feature` | Add a new feature block. |
| `rewrite_design` | Full script replacement (escape hatch). |
| `run_build` | Execute and emit STL/STEP/DXF/GLB; optional G-code slice. |
| `check_manufacturability` | Process-aware (`fdm` or `cnc`) report. |

Refusals come from the **AST audit** (security: no `os`, `subprocess`, network,
`exec`/`eval`, `__class__.__mro__`, etc.) and from real **sandbox build
failures** — not from a hand-coded matrix.

### Sandboxing

Every script runs in a separate Python subprocess:

- **AST audit** (`services/codegen/ast_audit.py`) parses the script and
  rejects unsafe imports, dunder access, exec/eval, file/network APIs.
- **Subprocess** (`services/codegen/sandbox.py`) launches with a stripped
  environment (no `ANTHROPIC_API_KEY` etc.), `cwd=/tmp/job_id`, no
  `PYTHONPATH` injection, `python -I` (isolated mode).
- **Resource limits** (`services/codegen/runner/host.py`) apply
  `RLIMIT_CPU = 90s`, `RLIMIT_AS = 4 GiB` before importing build123d.
- **Wall-clock timeout** = 120 s, after which the subprocess is hard-killed
  by `subprocess.run`.
- **Cloud Run** already uses gVisor; on macOS dev the above + the runner's
  isolated mode are the layers.

### Manufacturability — process-aware

`check_mesh(mesh, profile, process)` produces a `ManufacturabilityReport`:

- **FDM**: overhangs > 45°, sampled inward-ray min wall thickness, watertight
  + winding consistency, bed-size fit (per printer profile).
- **CNC**: undercuts (faces with `n.z < -0.1`), sharp internal corners
  (heuristic on adjacent face angles), watertightness, stock-size fit.

### Outputs

STL, GLB, **STEP** (CNC handoff), **DXF** (2D / waterjet / laser), G-code (FDM
via PrusaSlicer when `slice_gcode=true`).

### Snippet library

Pre-baked build123d idioms in `services/codegen/library/__init__.py`:
circular hole, **polygon hole** (triangle, hex, …), slot, circular pattern,
grid pattern, **hex grid**, fillet, chamfer, shell open-top, counterbore,
boss with hole, rounded box. Searchable via `query_library(intent)`.

## Phase 1: Pulsai chat agent

The new agent loop replaces the legacy single-prompt `/workspace/{id}/ai-edit`
path. It uses the Anthropic SDK directly (no proxy), calls a fixed set of
tools, and is gated by a per-template/source capability matrix.

### Required env vars

```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_CHAT_MODEL=claude-sonnet-5
ANTHROPIC_CLASSIFY_MODEL=claude-haiku-4-5-20251001  # used in Phase 2 routing
ANTHROPIC_FALLBACK_MODEL=claude-sonnet-4-6
ANTHROPIC_MAX_OUTPUT_TOKENS=1500
OPENAI_API_KEY=sk-...                               # optional jewelry concept generation
OPENAI_IMAGE_MODEL=gpt-image-1.5
DEFAULT_PRINTER_PROFILE_ID=prusa_mk4_default
```

`GEMINI_PROXY_URL` remains supported but is *legacy-only* and has no default.
If used, it must point to a runtime owned by this 3D Stack; another product is
never a dependency or credential source.

### Provider reliability and customer BYOK

Transient 429/5xx/529 failures use bounded exponential backoff with jitter,
`Retry-After`, a circuit breaker, and `ANTHROPIC_FALLBACK_MODEL`. The browser
can optionally send the customer's own Anthropic key for a CAD turn. The studio
also accepts request-scoped OpenAI, Gemini, Meshy, and Tripo keys for concept,
intent/image, and organic-mesh tasks. Keys stay in the current tab's memory;
only the selected provider key is sent, and it is not persisted. BYOK never
silently falls back to a Pulsai platform key.

See `docs/SECURITY_AND_SECRETS.md`, `docs/RUNBOOK_LINUX.md`, and
`docs/PRODUCTION_RUNBOOK.md` for Cloud Run Secret Manager verification, the
canonical VPS setup, and the no-traffic production release procedure.

### Tools available to the agent

| Tool | Purpose |
| --- | --- |
| `mutate_parameter` | Change one parameter on one feature. Validated against the capability matrix; refuses silent no-ops. |
| `add_feature` / `remove_feature` | Always refused in Phase 1; refusals carry a clear suggestion. Phase 2 will lift this. |
| `run_preview` | Rebuild GLB/STL, return revision id + mesh hash. |
| `check_manufacturability` | Mesh-based: min wall, overhangs, watertightness, bed fit. |
| `query_tree` | Read-only feature lookup. |

### Editability levels

Every workspace ships with a backend-enforced `EditabilityAssessment`
(`GET /workspace/{id}/editability`). The four levels are:

- **editable** — full parametric tree, all tools available.
- **partially_editable** — recognized features editable, opaque parts move with the model.
- **reference_only** — unrecognized imports; export is `as_is`, no geometry edits.
- **locked_unsafe** — manufacturability flagged the model invalid; export blocked until repair.

The same assessment populates the `EditabilityBadge` shown next to the model
name in the inspector.

### Upload format guidance

For editable CAD handoff, ask designers for **STEP/STP**. STEP preserves
solid/B-rep topology, so Pulsai can load it as `imported_part` and apply
build123d transforms, boolean cuts, mounting holes, and additive features.
Use **STL** for final print meshes only; STL is triangles, so edits are limited
to reconstruction, mesh booleans, repair, and reference workflows.

The preferred endpoint is `POST /design/import-cad`. The older
`POST /design/import-stl` route remains as a backward-compatible alias.

### CAD integrations

See `docs/CAD_INTEGRATIONS.md`. Current direction: **Onshape first** for direct
cloud CAD import, **Fusion STEP handoff first** with optional local Fusion MCP
bridge later. No CAD account or desktop install should be required for the core
maker flow.

### Printer profiles

The studio ships a curated FDM profile registry in
`backend/services/printer_profiles.py` covering common Prusa, Bambu, Voron,
Creality, Elegoo, Anycubic, and generic 0.4mm printers. Profiles drive bed-fit,
overhang messaging, and slicing defaults. Add new curated profiles there; user
custom/imported profiles should stay data-driven rather than hardcoded into UI
components. If a user's exact printer is missing, pick the closest bed/nozzle
match or the Generic 0.4mm FDM profile; this changes printability estimates and
slicer defaults, not the CAD geometry itself.

### ZIP export bundle

`POST /workspace/{id}/export-bundle` returns a manifest URL pointing at
`bundle.zip` containing:

- `model.stl` (or `preview.stl` for reference-only exports)
- `model.glb`
- `output.gcode` (skipped for reference-only)
- `manifest.json` — `{ model_name, revision_id, exported_at, source, editability_level, export_mode, printer_profile, parameter_values, manufacturability_report, mesh_hash, validation, software_version }`

The endpoint requires `expected_revision_id` and rejects with HTTP 409 if the
caller's expected revision is stale. This is the revision-truth guarantee:
exports always match what the user just saw in the viewer, never an older
preview.

## Tests

```
backend/tests/contracts/test_editability.py            # fast unit, no heavy deps
backend/tests/contracts/test_capability_matrix.py      # needs trimesh + cadquery
backend/tests/contracts/test_mesh_hash_changes.py      # opt-in: RUN_MESH_HASH_CONTRACTS=1
backend/tests/ai/evals/                                # ANTHROPIC_API_KEY required
frontend/tests/e2e/killer-flow.spec.ts                 # Playwright E2E
```

Frontend Playwright setup:

```
cd frontend
npm install              # picks up @playwright/test
npm run test:e2e:install # one-time browser install
npm run test:e2e
```

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

## License and user designs

The application source is licensed under **GNU AGPL-3.0-or-later**; see
[`LICENSE`](LICENSE). If you run a modified version as a network service, the
AGPL generally requires offering its users the corresponding source code for
that modified service. It does not, by itself, require users to publish the CAD
models, prompts, images, STL/STEP files, or G-code they create with Pulsai 3D.

“Pulsai” names and logos are not licensed as trademarks. Commercial licensing
for organizations that cannot use AGPL can be offered separately by the
copyright holder. This summary is practical project guidance, not legal advice.
