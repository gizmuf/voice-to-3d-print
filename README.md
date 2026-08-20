# Pulsai 3D

**Open-source, AI-first parametric CAD for turning an idea into an editable
model and manufacturing files.**

[![CI](https://github.com/gizmuf/voice-to-3d-print/actions/workflows/ci.yml/badge.svg)](https://github.com/gizmuf/voice-to-3d-print/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/gizmuf/voice-to-3d-print?include_prereleases)](https://github.com/gizmuf/voice-to-3d-print/releases)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/License-AGPL--3.0--or--later-blue.svg)](LICENSE)

[Try the hosted alpha](https://3d.pulsai.app) ·
[Roadmap](ROADMAP.md) ·
[Contributing](CONTRIBUTING.md) ·
[Share feedback](https://github.com/gizmuf/voice-to-3d-print/issues/new/choose)

Pulsai 3D lets you start from a description, a template, or an existing CAD
file; refine the result with parameters or conversation; inspect revisions and
manufacturability signals; and export STEP, STL, GLB, DXF, or optional FDM
G-code. The editable build123d/OpenCascade model is the source of truth. Meshes
and previews are derived artifacts.

> **Project status: public alpha.** The deterministic CAD path works without
> paid AI. The hosted alpha requires Google sign-in, and AI features normally
> require your own provider key unless account access was explicitly granted.
> Pulsai 3D is not safety-certified: independently review every model, slicer
> profile, and G-code file before manufacturing.

## Why Pulsai 3D

- **CAD-first, not mesh-only.** Parametric source, parameters, named features,
  revisions, and STEP exports remain connected.
- **Fast edits without an AI bill.** Numeric and deterministic edits run
  locally; AI is reserved for ambiguous or structural work.
- **Manufacturing-aware.** FDM and CNC heuristics, printer profiles, slicing,
  and export bundles live in the same workflow.
- **Open and self-hostable.** The application is AGPL-licensed, with local
  development and customer-owned provider keys supported.
- **Built with explicit safety boundaries.** Generated CAD code is audited and
  isolated, artifacts are owner-scoped, and platform-paid AI is off by default.

## What works today

| Area | Current capability |
| --- | --- |
| Start | Five starter designs, text prompts, build123d source, STEP/STP import, and STL fallback |
| Edit | Parameters, named-feature edits, full-script revisions, chat, and optional voice input |
| Inspect | 3D preview, revision history, feature context, and FDM/CNC manufacturability heuristics |
| Export | STEP, STL, GLB, DXF, FDM bundles, and optional PrusaSlicer G-code |
| Providers | Deterministic local path plus optional Anthropic, OpenAI, Gemini, Meshy, Tripo, Trellis2, and TripoSR integrations |
| Operations | Linux CI, secret scanning, owner isolation, private artifacts, backup/restore guidance, and a free CAD-to-print E2E |

STEP is the preferred editable interchange format. Imported STEP solids can be
transformed and augmented, but Pulsai does not promise perfect reconstruction
of every upstream feature tree. STL is a triangle mesh and has more limited
editability.

## Try it in five minutes

### Hosted alpha — no coding

1. Open [3d.pulsai.app](https://3d.pulsai.app) in Chrome or Safari.
2. Sign in with Google so projects and files stay private to your account.
3. Choose an example prompt such as the phone stand, speaker grille, pen holder,
   or box, then create the model.
4. Change one numeric parameter and confirm the preview and revision change.
5. Export a file if the workflow is useful to you.
6. [Report what worked or failed](https://github.com/gizmuf/voice-to-3d-print/issues/new/choose).

AI-assisted edits may ask for a provider key. You can still test starter
designs, deterministic parameter edits, previews, and much of the export flow
without a paid model call. See the
[non-coder testing guide](docs/HELP_WITHOUT_CODING.md) for a 10-minute checklist.

### Local development

Prerequisites: Git, Python 3.12, Node.js 22, and optionally PrusaSlicer for
G-code generation.

```bash
git clone https://github.com/gizmuf/voice-to-3d-print.git
cd voice-to-3d-print

cd backend
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
PULSAI_AUTH_REQUIRED=false \
PULSAI_INSECURE_LOCAL_DEV=true \
PULSAI_PUBLIC_SAFE_MODE=true \
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd voice-to-3d-print/frontend
npm ci
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000 npm run dev
```

Open [http://localhost:3000/design](http://localhost:3000/design). No provider
key is required for the deterministic starter-design path. For pinned Linux
dependencies, STT setup, production-safe configuration, and the full validation
gate, use [`docs/RUNBOOK_LINUX.md`](docs/RUNBOOK_LINUX.md).

## Architecture

```text
Next.js / React / Three.js
          |
          v
FastAPI API and owner-scoped project store
          |
          v
Audited build123d/OpenCascade CAD subprocess
          |
          +--> STEP / STL / GLB / DXF revisions
          +--> manufacturability checks
          +--> optional PrusaSlicer G-code
```

Harder natural-language edits can use a provider-backed agent. The agent calls
bounded CAD tools; successful builds persist source, parameters, mesh hashes,
and artifacts as a revision. Failed audits or builds do not silently replace
the last valid model.

Useful technical references:

- [`docs/EDITING_PIPELINE.md`](docs/EDITING_PIPELINE.md)
- [`docs/CAD_INTEGRATIONS.md`](docs/CAD_INTEGRATIONS.md)
- [`docs/SECURITY_AND_SECRETS.md`](docs/SECURITY_AND_SECRETS.md)
- [`SECURITY.md`](SECURITY.md)
- [Detailed product roadmap](docs/ROADMAP.md)

## Tests

The GitHub Actions workflow runs backend tests, frontend tests/lint/build, STT
security tests, dependency auditing, secret scanning, and a free browser
CAD-to-print flow. The current main branch is expected to keep that workflow
green.

For local checks:

```bash
cd backend
.venv/bin/python -m pytest -q tests \
  --ignore=tests/ai/evals/test_eval_runner.py \
  --ignore=tests/ai/evals_v2/test_eval_runner_v2.py

cd ../frontend
npm run test:unit
npm run lint
npm run build
```

Live provider evals are intentionally excluded because they can incur cost.
Run them only with an explicit budget and your own authorized credentials.

## Contributing

You do not need to be a CAD expert or a programmer. Useful contributions
include testing the hosted alpha, writing reproducible bug reports, improving
docs, adding printer profiles, and working on issues labeled
[`good first issue`](https://github.com/gizmuf/voice-to-3d-print/labels/good%20first%20issue).

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request. Please
report security issues privately using [`SECURITY.md`](SECURITY.md).

## License, user files, and commercial use

The application source is licensed under **GNU AGPL-3.0-or-later**; see
[`LICENSE`](LICENSE). If you offer a modified version over a network, the AGPL
generally requires offering the corresponding source of that modified service
to its users.

The license does not, by itself, require users to publish the CAD models,
prompts, images, exports, or G-code they create with Pulsai 3D. The “Pulsai”
names and logos are not granted as trademarks. A managed hosted service and
separate commercial licensing can coexist with the open-source project. This
paragraph is practical project guidance, not legal advice.
