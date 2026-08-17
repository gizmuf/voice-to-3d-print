# Pulsai 3D public roadmap

Pulsai 3D is a public alpha. The near-term goal is not feature count; it is a
short, trustworthy path from an idea to an editable and reviewable
manufacturing file.

## Shipped in v0.1

- build123d/OpenCascade source-of-truth CAD with isolated execution;
- five starter designs and deterministic parameter editing;
- conversational edits with customer-owned provider keys;
- STEP/STP and STL import with explicit editability limits;
- STEP, STL, GLB, DXF, and optional FDM G-code exports;
- revision history, mesh hashes, and manufacturability heuristics;
- private, owner-scoped hosted projects and artifacts;
- Linux CI, secret scanning, security policy, and a free CAD-to-print E2E;
- AGPL-3.0-or-later community edition.

## Now — first-user reliability

- make a fresh local install reproducible for new contributors;
- collect feedback from real maker, CAD, and non-CAD workflows;
- turn recurring feedback into small, testable issues;
- improve empty states, error messages, and no-key deterministic paths;
- publish small alpha releases with honest limitations and verification notes.

## Next — useful breadth

- more starter designs and hardware vocabulary;
- clearer STEP/STL editability explanations and import diagnostics;
- broader printer-profile coverage with contributor-friendly tests;
- accessibility and keyboard-flow improvements;
- one-command local development without weakening secure defaults;
- stable headless contracts for a future CLI, Python SDK, and MCP adapter.

## Later — sustainable product

- richer revision comparison and collaboration;
- managed queues, storage, backups, and team workspaces;
- expanded manufacturing checks and process handoff packages;
- optional hosted compute and commercial licensing for organizations that
  cannot use AGPL;
- a public design/gallery ecosystem with explicit opt-in publishing.

## Explicit non-goals

- claiming that generated models or G-code are universally safe;
- pretending arbitrary STL meshes recover a full parametric feature tree;
- hiding provider costs or silently spending a platform key;
- making customer models public by default;
- treating heuristic CNC checks as CAM or machine-ready toolpaths.

## How priorities are chosen

User evidence beats speculative scope. Priority increases when an issue is
reproducible, affects the core **describe → edit → inspect → export** loop, and
can be verified without paid-provider ambiguity. Public issues and releases
will record that maintenance work.

The longer engineering plan and decision history remain in
[`docs/ROADMAP.md`](docs/ROADMAP.md). They are planning material, not a promise
of dates or delivery order.
