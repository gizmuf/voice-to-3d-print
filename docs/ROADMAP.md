# Pulsai 3D — Full Roadmap

**One-line product:** describe a part, get a printable / millable model, edit by chatting. The chat is powered by Claude with build123d as the geometry engine; everything runs in a sandbox; the UI is three columns and stays that way.

**North-star metric:** time from "I have an idea" to "I have a printable file" under 2 minutes for a new user, under 30 seconds for a returning one.

## Positioning

Three taglines we own across audiences. The product page can rotate them; we don't water them down to a generic line:

- **For makers:** *Type what you need. Print it.*
- **For users (broad):** *CAD without learning CAD.*
- **For investors / partners:** *AI-native parametric CAD and manufacturing-prep layer.*

The category we are creating: **AI-first parametric CAD for makers, engineers, and non-CAD users.** Traditional CAD asks the user to learn the tool. Pulsai 3D lets the tool learn the user.

## The magic loop

Everything in this roadmap serves one feedback loop. If a feature doesn't make this loop tighter, we don't build it:

> **Describe → See model → Edit by words / sliders → Undo safely → Export printable file.**

Each phase is verified by replaying this loop end-to-end with the [Phase 0 flagship workflows](#phase-0--flagship-workflows-week-1) as fixtures.

---

## Where we are right now (May 2026)

The core engine works end-to-end:

- Code-driven CAD: every design *is* a build123d Python script in a sandbox.
- 9-tool agent loop (Claude Sonnet 4.6) with prompt caching.
- Three editing primitives: parameter mutation, surgical feature replacement, full rewrite.
- One macro tool (`mesh_modify_holes`) that proves the cost-cutting pattern (5× cheaper, 5× faster than letting Claude write the trimesh code).
- STEP-first CAD import (`/design/import-cad`) — STEP/STP for editable B-rep handoff, STL as mesh fallback.
- Bridge from legacy `/?workspace=` URLs into the powerful engine without breaking bookmarks.
- Inline parameter sliders + numeric inputs (no LLM call for tweaks).
- Per-turn cost transparency in chat (`$0.04 · 5,667 in / 439 out · rev abc12345`).
- Tool-result confirmation lines (✓ / ✕ with a one-sentence summary).
- Conversation auto-repair on dangling tool calls, persisted-history compaction.
- Deep-link to any past design via `?design=<id>`.

What is missing: discovery (how do new users find what to make?), trust (how do they undo confidently?), reach (real CAD file formats, real CNC support), and product (auth, billing, polish for paying users).

---

## Design principles — these gate every change in every phase

1. **Three columns. Forever.** Parameters / viewer / chat. No tabs, no nested panels, no modes. If a feature needs a fourth column it isn't ready.
2. **Defaults produce something.** Empty state always shows examples. Never a blank canvas.
3. **Every action is reversible.** Revisions are commits; the timeline is the undo button.
4. **Confirmations are visible.** Every tool call shows ✓ or ✕ with one human sentence. Every parameter change re-renders the model.
5. **Cost is visible.** Each chat turn shows the dollar amount and the token breakdown.
6. **Speed beats control.** Common path must be fast. Depth lives behind one click, never two.
7. **Words match the user's words.** "Holes," not "extrude profiles." "Make it bigger," not "uniform scale ratio."
8. **No login until necessary.** Anonymous works as long as the user's session lives.
9. **No modes.** Direct manipulation. No "select-the-tool-then-click."
10. **Avoid dialogs.** Confirmations happen inline as result lines, not blocking modals.

These principles are guardrails against the failure mode the user named: "not like other programs." Cluttered CAD UIs lose to chat-first UIs because they ask the user to learn the tool. We want a tool that learns the user.

---

## Phase 0 — Flagship workflows *(week 1)*

**Goal:** lock in 5 representative designs as the integration tests for every phase. Every phase from 1 onward must keep all 5 working through its verification gate. Stops generic CAD plumbing from drifting away from real maker use cases.

The five workflows:

1. **Wall hook** — flat plate + hook arm + screw holes. Most-printed object on the planet, tests fillets + counterbore.
2. **Phone stand for iPhone-class device** — angled, cable hole, lip. Tests angles + assembly fit.
3. **Cylindrical knob** — knurled grip + threaded insert hole. Tests rotational symmetry + small features.
4. **Mounting bracket (right-angle)** — two flat faces with elongated slots. Tests CNC-friendly geometry + slots.
5. **Enclosure box (electronics)** — open-top with screw bosses, USB cutout, vents. Tests boolean ops + multi-feature compositions.

**Files:**
- `backend/data/flagship/{wall_hook,phone_stand,knob,bracket,enclosure}.json` — design seeds.
- `backend/services/codegen/flagship.py` — load helpers used by Phase 0 verification.
- `backend/tests/flagship/test_round_trip.py` — for each, "build → edit one parameter → build → mesh hash differs" smoke test. Runs on every PR.

**UX:** in Phase 3 these become the first 5 entries of the gallery. They're not "demo content" — they're the integration test set that survives every refactor.

**Verification:** all 5 build cleanly on a fresh checkout in <30 s each. Every smoke test in every later phase loops through these.

---

## Phase 1 — Power & Trust *(weeks 2–3 from start)*

**Goal:** every common edit is fast, cheap, and visibly confirmed. Make Claude correctly route to a one-shot tool for the 80% of asks; make undo a single click. Trust > power: a user who can confidently break and undo will explore further than one given more buttons.

### Deliverables

#### 1.1 Macro tool library expansion
Same pattern as `mesh_modify_holes`: 8-12 lines of LLM output → one tool call → 3-5× cost reduction per request. Each tool is a self-contained Pydantic input + a `# @feature: …` block appended to the script.

| Tool | Use case |
|---|---|
| `mesh_split_at_plane` | "split this in half so I can print it in two pieces" |
| `mesh_offset_surface` | "make it 0.2mm bigger everywhere for press-fit tolerance" |
| `mesh_smooth` | "smooth the rough edges from this STL" |
| `mesh_decimate` | "this STL is 10 MB, reduce the polygon count" |
| `mesh_repair` | "this STL has holes / non-manifold edges, fix it" (wraps existing MeshLib) |
| `mesh_subtract_primitive` | "subtract a 6mm cylinder at (10, 20, 0)" |
| `mesh_add_primitive` | "add a 4mm boss at the corner" |
| `mesh_mirror` | "mirror this part along the X axis" |
| `detect_features` | returns list of `[{kind: hole, position, radius}]` so Claude can target specific ones |
| `auto_orient_for_fdm` | rotate the part so the largest flat face sits on the build plate |

**Files:**
- `backend/services/ai/tools_v2/{mesh_split_at_plane,mesh_offset_surface,mesh_smooth,mesh_decimate,mesh_repair,mesh_subtract_primitive,mesh_add_primitive,mesh_mirror,detect_features,auto_orient_for_fdm}.py` (new)
- `backend/services/ai/tools_v2/__init__.py` (register)
- `backend/services/ai/prompts_v2.py` (teach the agent when to prefer the macro)
- `backend/tests/ai/evals_v2/cases/cases.json` (eval case per tool)

**Success:** median chat turn drops from $0.05 to $0.02; "modify imported STL" prompts complete in 2 tool calls or less.

#### 1.2 Revision timeline
Thumbnails of past revisions in a horizontal strip above the viewer. Click to load that revision (becomes a fork branch from there). Already on disk at `data/output/designs/{id}/revisions/{rev_id}/build.json`.

**Files:**
- `backend/app.py` — `GET /design/{id}/revisions` (list with metadata + per-revision GLB/thumbnail URLs)
- `backend/services/codegen/store.py` — list revisions helper
- `frontend/components/Design/RevisionTimeline.tsx` (new)
- `frontend/components/Design/DesignStudio.tsx` (slot above the viewer)

UX: 6-8 thumbnails visible; older ones collapse with a "show more" affordance. Clicking is the undo button. Hovering shows the timestamp + any chat message that produced that revision.

**Success:** "undo" stops requiring a chat turn ($0.05 → $0); revisions become first-class.

#### 1.3 Live re-render on slider drag (opt-in)
Today the slider commits on mouse-up. Add a small "live preview" toggle in the inspector header. When on, drag fires `/design/{id}/parameter` debounced at 200ms.

**Files:**
- `frontend/components/Design/DesignStudio.tsx` (toggle state, debounced update)
- (no backend change — endpoint already exists)

UX: off by default for parts that take >2s to rebuild (we know from `last_build.duration_ms`). Toggle is a single switch; the user opts in.

**Success:** for fast designs, parameter tweaks feel like a slider in any modeling app.

#### 1.4 Print cost / time estimator
*(Moved up from Phase 5 — high trust value, low effort.)* PrusaSlicer already returns weight + time in its sliced output. Surface them per build: "12 g · ~$0.18 · 47 min." Configurable filament price. Inspector shows it under manufacturability.

**Files:**
- `backend/slicer_service.py` — parse weight + duration from PrusaSlicer stdout.
- `backend/services/codegen/models.py` — add `estimated_filament_g`, `estimated_print_min`, `estimated_cost_usd` to Build.
- `frontend/components/Design/DesignStudio.tsx` — show beneath the manufacturability panel.

**Why now, not Phase 5:** users decide whether to print based on cost. Knowing it before hitting Build closes a real friction loop. The data is free; the UI is two lines.

#### 1.5 Eval harness coverage for macros
One eval case per macro tool, run on every PR. Catches regressions when we upgrade the agent prompt or model.

**Files:**
- `backend/tests/ai/evals_v2/cases/cases.json` (extend)
- `backend/tests/ai/evals_v2/test_eval_runner_v2.py` (already runs all cases)

#### 1.6 Feature graph v1
Promote `NamedFeature` from a flat script-block list into a small persistent graph. Each feature gets a stable ID, parent links, creation source, original user wording, source prompt, and first revision ID. This turns later selection, diff, and gallery-fork behavior into structured data instead of comment-string matching.

**Files:**
- `backend/services/codegen/models.py` — extend `NamedFeature`.
- `backend/services/codegen/runner/host.py` — emit structured feature sidecar metadata.
- `backend/services/codegen/store.py` — persist and load the feature graph with the build snapshot.
- `backend/services/ai/tools_v2/{append_feature,replace_feature}.py` — write graph metadata when creating or replacing feature blocks.

**Success:** a generated feature has a stable `id`, `parent_feature_ids`, `created_by`, `source_prompt`, `revision_id`, and `user_words`; the ID survives script regeneration and revision restore.

#### 1.7 Cost-tier badges on chat input
The `/route-intent` endpoint exists; make it visible before the user sends. Debounce the current draft through the router and show one small badge: `Free edit` for direct parameter updates, `Cheap edit` for high-confidence macro routes, or `Full rebuild` for agent-loop fallbacks.

**Files:**
- `frontend/components/Chat/ChatPanel.tsx` — call `/route-intent` on debounced input and render the badge.
- `backend/app.py` — verify `/route-intent` stays free of LLM calls and cheap under repeated preview use.

**Success:** parameter/slider-language asks show the free/cheap badge before send, and median cost for those asks is ≤$0.02.

#### 1.8 Structured selected-feature context
The frontend currently appends `[Selected feature: ...]` into the chat body. Replace that hack with structured context so the agent receives a clean selected-feature block and can prefer that feature unless the user says otherwise.

**Files:**
- `backend/app.py` — add `selected_feature_id: str | None` and optional label to `DesignChatRequest`.
- `backend/services/ai/agent_v2.py` — inject selected-feature context into the agent prompt.
- `frontend/components/Chat/ChatPanel.tsx` — send the structured field instead of relying on inline tags.

**Success:** clicking/selecting a feature and typing "make it 5mm" edits the selected feature without parsing bracketed text out of the user message.

#### 1.9 Revision diff summary
Compute a diff between a revision and its parent from the existing parameter snapshots, mesh/build metadata, and the Phase 1.6 feature graph. Surface the short diff in the revision timeline hover state.

**Files:**
- `backend/services/codegen/diff.py` (new) — parameter and feature add/remove diff helpers.
- `backend/app.py` — `GET /design/{id}/revisions/{rev_id}/diff`.
- `frontend/components/Design/RevisionTimeline.tsx` — hover popover with changed params, feature changes, rebuild time, and cost when available.

**Success:** hovering a revision shows what changed, for example `hole_diameter_mm: 4 -> 5`, plus feature additions/removals and rebuild/cost metadata when present.

#### 1.10 Locked parameters
Add a user lock to parameter specs. Locked parameters render with a lock icon, are listed in the agent context, and are rejected server-side for `update_parameter` unless the user explicitly unlocks or overrides.

**Files:**
- `backend/services/codegen/runner/host.py` — accept `locked=True` in `pulsai.param(...)`.
- `backend/services/codegen/models.py` — add `DesignParameter.locked`.
- `backend/services/ai/tools_v2/update_parameter.py` — reject locked parameter changes unless explicitly overridden.
- `frontend/components/Design/ParameterControl.tsx` — lock icon, tooltip, and toggle.

**Success:** a locked parameter cannot be changed by slider-language chat or tool calls until unlocked, and the user sees the lock state in the inspector.

#### 1.11 Geometry-based eval checks
Upgrade Phase 1.5 evals from "mesh hash changed + expected tool called" to geometry-property predicates. Seed checks include `buildsSuccessfully`, `isWatertight`, `boundingBoxMm` with tolerance, `holeCount`, and `minWallThicknessMm`.

**Files:**
- `backend/tests/ai/evals_v2/checks.py` (new) — predicate library over build results and manufacturability scans.
- `backend/tests/ai/evals_v2/test_eval_runner_v2.py` — accept richer check schema.
- `backend/tests/ai/evals_v2/cases/cases.json` — add seed examples for bbox, hole count, watertightness, and wall thickness.

**Success:** evals catch wrong dimensions, wrong feature count, non-watertight output, and unprintable walls even when the mesh hash changes.

**Verification for Phase 1:**
- Smoke test each macro on a representative design. Mesh hash changes confirm geometry effect.
- Per-turn cost on `make holes 1mm smaller` averages $0.02-0.03 (vs $0.04-0.05 today).
- Click any thumbnail in the revision timeline → the model loads and the inspector reflects that revision.
- Slider live mode toggled on, drag a value → 3D re-renders within ~300ms for simple parts.
- Feature graph metadata survives append, replace, restore, and fork flows.
- Selected-feature context reaches the agent as structured data, not a bracketed chat string.
- Geometry-based eval checks pass in `pytest backend/tests/ai/evals_v2/`.

---

## Phase 2 — Real Inputs *(weeks 3-4)*

**Goal:** real designs from real CAD users. The pro-CAD file format (STEP), the moments where users want documentation, and the "I know what I want, just put it on the canvas" path.

### Deliverables

#### 2.1 STEP import — *honest scope*

The format every Fusion / SolidWorks / Onshape user exports for sharing. `build123d.import_step` returns a Compound that can round-trip through our codegen path.

**What we promise to users (be specific in the UI and docs):**

> **"Import any STEP file. Inspect, measure, transform, and export. Edit features that we recognize. Boolean-modify with new geometry."**

**What we explicitly do NOT promise:**

> **"Edit any feature in any STEP file like Fusion does."**

Real STEP files vary in topology and naming; full B-rep round-trip editing is a multi-quarter problem. Overpromising loses pro-user trust on day one. Underpromising lets us ship something useful.

**STEP capability tiers** (shown to the user as the editability badge already does for STL):

| Tier | What works | What doesn't |
|---|---|---|
| **inspect** | view, measure, manufacturability check, export-as-is | any geometry edit |
| **transform** | translate, rotate, scale the whole part | per-feature edits |
| **augment** | boolean union/subtract with build123d primitives, fillet/chamfer the outer edges | edit the original features |
| **edit** | recognized parametric features (holes, slots, bosses) become editable | unrecognized features stay opaque |

The auto-detected tier is shown in the editability badge. Most STEP files land at "augment"; that's still useful.

**Files:**
- `backend/app.py` — preferred `/design/import-cad` endpoint, with `/design/import-stl` kept as a compatibility alias
- `backend/services/codegen/templates/__init__.py` — add `IMPORTED_STEP` starter script (uses `imported_part` instead of `imported_mesh`)
- `backend/services/codegen/runner/host.py` — pre-load STEP into namespace
- `frontend/components/Design/DesignStudio.tsx` — accept `.step` / `.stp` in the file input

UX: STEP/STP is the recommended upload for editable CAD handoff. STL remains accepted, but the UI labels it as a final triangle mesh with limited reconstruction / mesh-boolean edits.

**Success:** real CAD users from Fusion/SolidWorks can drop their STEP file in and edit it.

#### 2.2 Multi-process export
Today STL+GLB ship by default; G-code / STEP / DXF on demand. Replace the per-format buttons with one "Export for…" picker:
- **3D printing (FDM)** → STL + G-code + manifest.json
- **CNC milling** → STEP + DXF (handoff to user's CAM tool)
- **Documentation** → PNG render (top + iso views) + dimensioned PDF
- **Everything** → ZIP with all of the above

**Files:**
- `backend/services/export_bundle.py` — extend with format-set logic
- `backend/app.py` — `/design/{id}/export` accepting a `preset` enum
- `frontend/components/Design/DesignStudio.tsx` — single button instead of multiple chips

UX: one button, one click, right files. The user picks "what for" not "which format." Hides the file-format zoo behind their goal.

**Success:** new users don't have to know what STEP, DXF, G-code, GLB are. Power users still get them.

#### 2.3 Snippet → starter cards (free path)
When `query_library` matches an idiom, surface those matches as cards in the chat that the user can click directly to insert (without paying for an Anthropic call). This builds parallel paths: "I know what I want" → click → free; "I'll describe it" → chat → costs.

**Files:**
- `frontend/components/Design/SnippetSuggestions.tsx` (new — fetched from `/design/library?q=…`)
- `backend/app.py` — `/design/library` endpoint (already-implemented `services.codegen.library.search`)

UX: when the user hovers over their parameters or the viewer, suggested snippets appear in a small dropdown ("Add: counterbore · slot · circular pattern"). One click inserts via `append_feature` directly (skip the LLM).

**Success:** repeat operations like "add 4 mounting holes" become one click.

#### 2.4 Mini-gallery (5 starter forkable designs)

*(Pulled forward from Phase 3 to cover the "what do I make?" gap that real CAD users don't have but new users do.)* The five flagship workflows from Phase 0 become forkable cards on the studio empty state. Click any → opens that design pre-built. Full curated gallery (~30-50 designs) still lands in Phase 3.

**Files:**
- `frontend/components/Design/DesignStudio.tsx` — render flagship cards alongside prompt + STL import on the empty state.
- `backend/app.py` — `/design/flagship` endpoint listing the 5 with thumbnails.

**UX:** the empty state already has prompt textarea + STL import + 4 quick-prompt chips. Add a "Start from a template" row of 5 thumbnails. Total empty state: prompt + import + chips + 5 starter cards. Still readable in one glance.

**Why pulled forward:** GPT's review correctly noted that if the first paying users are non-CAD makers, gallery should come earlier than STEP. We address both audiences in Phase 2 — pros get STEP, makers get the 5 starter cards — without delaying STEP.

#### 2.5 Click-in-viewer feature selection
Three.js raycast on click → identify which named feature owns the clicked face → highlight in the inspector. Bidirectional with chat: clicking a feature in the inspector also frames it in the viewer.

**Files:**
- `backend/services/codegen/runner/host.py` — tag GLB faces with feature name (Three.js userData)
- `frontend/components/ModelViewer.tsx` — emit selection events on click
- `frontend/components/Design/DesignStudio.tsx` — wire selection ↔ inspector

UX: makes "the holes" (chat-language) and the actual geometry connect visually. Critical for designs with many features.

**Success:** "make this hole bigger" works when the user clicks the hole and types "5mm" — Claude knows which one because the chip carries the feature ID.

#### 2.6 Hardware vocabulary library
Add data-driven manufacturing presets so users can speak in real hardware intent: "M3 hole", "608 bearing", "heat-set insert for M3", "USB-C cutout". These become snippets available to `query_library` and chip suggestions in the snippet UI.

Initial bundle:
- M2 / M2.5 / M3 / M4 / M5 / M6 screw clearance, tap, counterbore, and countersink dimensions.
- Common bearings: 608, 624, 625, and 6800-series OD/ID/width.
- Heat-set inserts for M2-M5.
- Disc magnets: 6x3, 8x3, 10x3, 12x3 mm.
- Cable cutouts: USB-A, USB-C, micro-USB, barrel jack 5.5x2.1, RJ45.

**Files:**
- `backend/services/codegen/library/hardware/{screws,bearings,inserts,magnets,cables}.py` (new).
- `backend/services/codegen/library/__init__.py` — register the hardware bundle.

**Success:** "add four M3 screw holes" and "make a 608 bearing pocket" route through library presets with correct dimensions and no custom geometry guessing.

#### 2.7 Make printable one-click
Bundle existing print-prep pieces behind one manufacturability-panel action: `mesh_repair`, `auto_orient_for_fdm`, manufacturability scan, and FDM export preset. Return a downloadable bundle and one concise result row.

**Files:**
- `backend/app.py` — `POST /design/{id}/make-printable`.
- `frontend/components/Design/ManufacturabilityPanel.tsx` — button, progress state, and result row.

**Success:** one click produces a printable FDM bundle and a summary like `Repaired 1 non-manifold edge · oriented largest face down · sliced at 0.2mm · 12g · 47min`.

**Verification for Phase 2:**
- Upload a STEP file from Fusion → renders in viewer, edits via chat work.
- "Export for CNC" → ZIP contains STEP + DXF, no G-code.
- Click the `pattern` feature in the viewer → inspector highlights it; chat picks it up as selected feature.
- Hardware vocabulary prompts map to preset dimensions without hand-entered numbers.
- Make printable returns a ZIP and a one-line repair/orientation/slice summary.

---

## Phase 3 — Discovery & Onboarding *(weeks 5-7)*

**Goal:** a new user lands and produces something printable in under 2 minutes. The empty state stops being scary.

### Deliverables

#### 3.1 Built-in design gallery
Curated library of 30-50 forkable designs across categories (organizers, mounts, replacement parts, decorative, mechanical). Each is a saved Design with parameters; clicking forks it.

**Files:**
- `backend/data/gallery/*.json` — gallery seeds
- `backend/services/codegen/gallery.py` — load + fork
- `backend/app.py` — `/gallery` endpoint
- `frontend/app/(gallery)/page.tsx` — grid of cards
- `frontend/components/Gallery/GalleryCard.tsx`

UX: gallery is its own page (`/gallery`) but accessible via a button on the studio empty state. Each card shows a thumbnail + 5-word description. Click → opens that design in the studio with one revision (the seed). No commitment — fork freely.

**Success:** new users have starting points. "What can I make?" gets answered visually.

#### 3.2 First-run guided tour
Three 1-second beats on first visit:
1. The prompt box ("describe what you want")
2. The viewer ("see it instantly")
3. The chat ("refine by talking")

**Files:**
- `frontend/components/Onboarding/Tour.tsx` (lightweight, dismissible, localStorage flag)

UX: spotlight + arrow + sentence. No multi-step "click here, now click here" — just three seconds of orientation.

**Success:** first prompt is sent within 30 seconds of landing.

#### 3.3 Empty-state by use case
Replace the four chip buttons with eight grouped by intent:
- **Functional:** Mounting bracket · Phone stand · Pen holder · Knob
- **Decorative:** Speaker grill · Vase · Picture frame · Ornament

Each chip auto-fills the prompt and triggers Generate.

**Files:**
- `frontend/components/Design/DesignStudio.tsx` (data-only change)

UX: organized by *why* a user would make this. Discoverable without being overwhelming.

#### 3.4 Inline help (tooltips)
Hover any parameter or feature name → tooltip with the param's `doc` string + a 1-line "what this does." Already exposed via `pulsai.param(doc=…)`; just renders nicer.

**Files:**
- `frontend/components/Design/DesignStudio.tsx` (tooltip wrapper)

UX: progressive disclosure. Help is one hover away, never in the way.

#### 3.5 Mobile-responsive read-only viewer
At <900px width, stack to a single column with viewer first, parameters collapsed by default, chat below. Editing disabled (touch-edit on a 5" screen is bad UX); the user can view + share.

**Files:**
- `frontend/components/Design/DesignStudio.tsx` (CSS queries)

UX: landing on a phone shows your design without breaking. Useful for sending links to friends / colleagues.

**Verification for Phase 3:**
- Cold visit → first design produced in <2 minutes.
- Gallery card click → fork loads in <5 seconds with seeded thumbnail.
- Mobile (375px viewport) → page renders with viewer + parameters readable.

---

## Phase 4 — Power Inputs *(weeks 8-10)*

**Goal:** photo, sketch, voice as input modalities. Removes the "I don't know what to type" barrier.

### Deliverables

#### 4.1 Image-to-design — *honest scope*

Photo of a part / hand sketch → Claude reads it (vision API) → generates a build123d script. Constrained generation: the output is parametric build123d, not a mesh from Meshy/Tripo.

**What we promise:**

> **"Generate a rough editable starting point from a photo or sketch. Refine it by chat or sliders."**

**What we don't promise:**

> **"Photogrammetry-quality CAD reconstruction from a single image."**

Single-image inverse CAD is unreliable; pretending otherwise burns trust. The right framing is "starting point I can refine," not "finished part."

**Clarifying-question pattern.** When dimensions are missing from the image (always), Claude asks for *one reference dimension* before producing geometry:

> *"I can see a coat hook with two screw holes and a curved arm. What's the total width? Once I know that, I can scale everything proportionally."*

This is the right product behavior because:
- It mirrors real designer workflow (you always need one anchor)
- It surfaces the model's uncertainty honestly
- It produces a usable result instead of a guess

**Files:**
- `backend/services/ai/tools_v2/read_image.py` (wire up `client.messages.create(content=[{type:"image",…}])`)
- `backend/services/ai/prompts_v2.py` — "ask for one reference dimension before generating from an image" rule
- `frontend/components/Design/DesignStudio.tsx` — image upload alongside the prompt textarea

**Success:** user uploads a photo of a coat hook + types "total width 80mm" → gets an editable design within one chat turn that approximates the photo at the right scale.

#### 4.2 Voice input
Mic button on the chat input. Browser SpeechRecognition (free) by default; Deepgram (already configured) for accuracy when enabled.

**Files:**
- `frontend/components/Chat/ChatPanel.tsx` — mic button (reuse parts of legacy VoicePanel)

UX: click-to-talk. Transcript fills the textarea; user reviews and sends.

**Success:** spoken prompts work. Useful when sketching while talking.

#### 4.3 Reference-image attached to chat turns
Drop an image onto the chat panel → Claude sees it as part of the next message. Useful for "make it look like *this*" or "the holes should match this pattern."

**Files:**
- `frontend/components/Chat/ChatPanel.tsx` — image attachment chip
- `backend/services/ai/agent_v2.py` — embed image content blocks in the user message

**Success:** "match this pattern" works without typing the description.

**Verification for Phase 4:**
- Photo of a coat hook → editable design within 1 chat turn.
- Voice "make the holes triangles" → script edits + mesh changes.

---

## Phase 5 — Manufacturing Polish *(weeks 11-14)*

**Goal:** outputs that pros use without rework. The "actually print / mill it" experience.

### Deliverables

#### 5.1 Print cost / time estimator
PrusaSlicer already returns these in metadata. Surface them per build: "12 g filament · 47 min · ~$0.18". Configurable filament price.

**Files:**
- `backend/slicer_service.py` — parse PrusaSlicer output
- `backend/services/codegen/models.py` — add fields to Build
- `frontend/components/Design/DesignStudio.tsx` — show below manufacturability panel

#### 5.2 Multi-printer profiles
Bambu X1, Ender 3, Prusa MINI added as PrusaSlicer config drops. Profile picker in the inspector header.

**Files:**
- `backend/services/printer_profiles.py` (already in place; add 3 more)
- `backend/printer_profiles/*.ini` (PrusaSlicer config files per printer)
- `frontend/components/Design/DesignStudio.tsx` — printer dropdown

#### 5.3a CNC handoff package *(achievable in Phase 5)*

Real CAM (toolpath G-code generation) is a different and harder world: tool diameter, material, feeds and speeds, workholding, stock setup, tool changes, post-processors, machine safety. Doing it well is multi-month. Doing it badly hurts users and people's machines.

What we *can* do well, now: a **CNC handoff package** that gets a CAD-ready user from Pulsai 3D into their existing CAM tool (Fusion 360, HSMWorks, MeshCAM, kiri:moto, F-Engrave, etc.) without rework:

- **STEP** of the part
- **DXF** of any 2D outline / pocket profile
- **Setup notes PDF**: dimensions, hole positions + sizes, suggested tool list, recommended stock size, orientation, units
- **Manifest**: part name, revision, exported_at, designer notes

This positions Pulsai as the **CAD + manufacturing-prep layer**, not a CAM replacement — which is the honest and useful framing.

**Files:**
- `backend/services/export_bundle.py` — extend with CNC preset that includes the dimensioned PDF
- `backend/services/codegen/cnc_setup_notes.py` (new — generate the PDF via WeasyPrint or matplotlib)
- `frontend/components/Design/DesignStudio.tsx` — CNC option in the export picker

#### 5.3b CNC toolpath generation *(deferred — Phase 7+)*

Actual G-code generation from STEP via [pycam](https://github.com/SebKuzminsky/pycam) or [kiri:moto](https://github.com/GridSpace/grid-apps) is a multi-month project (post-processors per machine, tool library, fixturing). We **explicitly do not let it block** Phases 5/6. It ships when:

- We have CNC users actively asking for it (signal from sharing / forum traffic)
- We can dedicate 6+ weeks to it without delaying the rest
- We've shipped the handoff package (5.3a) and seen what users actually use

**Files (when it lands):**
- `backend/services/cam/__init__.py` (pycam wrapper or kiri:moto subprocess worker)
- `backend/app.py` — `/design/{id}/cam` endpoint
- Per-machine post-processor configs in `backend/cam_profiles/*`

#### 5.4 Multi-revision side-by-side compare
Pick any two revisions from the timeline → split-pane viewer showing both. Useful for "should I use 4 or 6 rings?" decisions.

**Files:**
- `frontend/components/Design/CompareView.tsx` (new)
- `frontend/components/Design/DesignStudio.tsx` — "compare" mode toggle on the timeline

#### 5.5 Auto-orient for FDM
Already in Phase 1's macro list. Confirms the part sits on its largest flat face automatically.

**Verification for Phase 5:**
- A real print succeeds with FDM G-code from the studio.
- A real CNC mill cuts the STEP/G-code from the studio.
- Print cost estimate within ±15% of PrusaSlicer's slicer detail.

---

## Phase 6 — Make It a Product *(weeks 15-20)*

**Goal:** paying users. Required only after the product is sticky enough that someone will pay.

### Deliverables

#### 6.1 Auth
Clerk (drop-in components, $25/mo for 10k MAU) is the recommended path. Anonymous still works; sign-in unlocks saved projects + sharing.

**Files:**
- `backend/app/middleware/auth.py` (new — Clerk JWT verification)
- `frontend/app/layout.tsx` — `<ClerkProvider>` wrapper
- `frontend/components/Header/UserMenu.tsx` (new)

UX: a small "Sign in" link top-right. No forced login. Anonymous designs auto-attach to the user on first sign-in.

#### 6.2 Stripe
Checkout + Customer Portal + webhook. Single tier ($19/mo) at launch. Per-user monthly cost ceiling enforced server-side.

**Files:**
- `backend/app/api/billing.py` (new)
- `frontend/app/(billing)/page.tsx` — pricing page

#### 6.3 Per-user quotas
Redis (Cloud Memorystore $30/mo) for atomic counters. Snapshot to Firestore daily.

**Files:**
- `backend/app/middleware/quota.py` (new)

#### 6.4 Public design sharing
A `Share` button on each design that publishes a read-only public URL. Public designs feed the gallery (Phase 3.1) over time.

#### 6.5 Team workspaces (Studio tier)
Owner + member RBAC, shared design library. Defer until sign-ups demand it.

**Verification for Phase 6:**
- 5 paying subs in the first 2 weeks of launch.
- Anonymous → sign-in → designs migrate to user account cleanly.
- Webhook round-trips work end-to-end.

---

## Cross-cutting concerns *(throughout all phases)*

These ride along with feature work; not separate phases.

### Performance
- GLB streaming (don't block viewer on full file)
- Preview rebuild cache keyed by `(script_hash, parameter_snapshot)` — avoids rebuilding on undo / fork-from-revision
- Mesh thumbnail generation at build time (used by gallery + revision timeline)
- Cold-start mitigation on Cloud Run: `min_instances=1` always; pre-warm build123d in image

### Reliability
- Eval harness expanded with each macro tool
- Sandbox subprocess crash recovery (already partial; expand)
- Budget gate: hard cap per anonymous session ($1/day) and per signed-in user ($X/month based on tier)
- Rate limit on chat endpoint (60 turns/hour anonymous)

### Accessibility
- Keyboard navigation through the inspector (arrow keys + enter)
- Screen reader labels on all interactive controls
- Focus-visible outlines (currently CSS minimal)
- Reduced-motion support (no auto-rotate when `prefers-reduced-motion`)

### Telemetry
- Anonymous usage analytics: which prompts succeed, which tools get called, error rates, drop-off points
- Per-tool success rate dashboards (admin only)
- Cost-per-prompt tracking (informs future macro tool priorities)

### Documentation
- Inline help (Phase 3.4)
- Public landing page at `pulsai3d.com` (Phase 6 alongside billing)
- README + architecture docs (kept up to date as features land)

### Internationalization
- Defer to Phase 7+. UI strings centralized so a future i18n pass is mechanical.

---

## What NOT to build *(explicitly deferred)*

These are the "tempting but wrong" items. Listing them so we don't waste cycles later wondering.

- **Tabs / multi-pane workspace.** Three columns is the design. Tabs hide state.
- **Plugin system.** Premature; we don't know which extension points matter.
- **Custom user CadQuery code in production.** Sandboxing arbitrary Python beyond the AST audit is multi-week security work; no clear user demand.
- **Real-time multi-user collaborative editing.** Niche; high engineering cost. Comments-on-revisions covers most of the social need.
- **BYOK (bring-your-own-key) model selector.** Adds settings UI for ~3% of users.
- **Native desktop app.** Web-first is right; PWA is sufficient if offline matters.
- **Mobile editor.** Read-only viewer (Phase 3.5) is enough; touch CAD is bad CAD.
- **Custom languages beyond build123d.** OpenSCAD / Fusion macros / Onshape FeatureScript would dilute the core. build123d covers what we need.
- **AI explanation / "why did you choose this?" panel.** Verbose; the chat reply is the explanation.
- **Live cursor / presence.** Same niche as collaborative editing.

---

## Open questions to resolve before each phase

These need a 30-second decision from you, not a planning meeting.

### Before Phase 2
- STEP-edit fidelity expectation: do we promise "edit any STEP file" or "edit STEP files we recognize the structure of"? (Answer affects scope by ~2 weeks.)
- Documentation export format: PDF (PrintWeaver / WeasyPrint) or just PNG renders?

### Before Phase 3
- Gallery curation: who maintains it? Initial 30 from us; community-submitted later. Approval workflow needed?

### Before Phase 4
- Image-to-design constraints: do we commit to *parametric* output (build123d script) or allow mesh-only output for "I just want a 3D print of this photo"? Different products.
- Voice: browser SpeechRecognition default vs Deepgram default? Browser is free but worse accuracy.

### Before Phase 5
- CNC toolpath: pycam (Python, more flexible, less polished) or kiri:moto (battle-tested, JS, integration is heavier)?
- Per-printer profiles: just MK4/MINI/Bambu/Ender, or open it up to a community-maintained set?

### Before Phase 6
- Pricing: $19/mo flat, or tiered (Free / $19 Pro / $49 Studio)? Original plan was tiered; might consolidate.
- Auth: Clerk ($25/mo SaaS) vs Firebase Auth (build the UI, ~5 days)?

---

## Phase order rationale

Why this ordering and not, say, billing first?

1. **Phase 1 (Power & Trust)** before everything because it makes every subsequent prompt cheaper and every undo free. Pays for itself in week one.
2. **Phase 2 (Real Inputs)** before discovery because real-CAD users (the high-value segment) need STEP support before they'll seriously try the product.
3. **Phase 3 (Discovery)** before power inputs because most new users churn at "what do I make?" — the gallery and tour solve that.
4. **Phase 4 (Power Inputs)** is amplification of an already-converting product. Image / voice expand the funnel; they don't fill it.
5. **Phase 5 (Manufacturing Polish)** is when the product transitions from "neat AI demo" to "I will use this for real work." Until Phase 4, users are exploring; Phase 5 makes the outputs serious.
6. **Phase 6 (Make It a Product)** lands when the existing free product gets organic word-of-mouth. Premature billing kills the funnel; late billing is fine.

If user feedback after Phase 1 says the bottleneck is something else, reorder. The phases are a default sequence, not a contract.

---

## Verification gates per phase

Each phase ends with a 30-minute verification ritual:

1. **Smoke test** — fresh anonymous user, the phase's signature flow, end-to-end with no errors.
2. **Eval harness** — `pytest backend/tests/ai/evals_v2/` passes ≥90% with no degradation in median cost.
3. **Manual UX walk** — three-paragraph note on what feels right and what doesn't. Saved to `docs/walkthroughs/phase-N.md`.
4. **Cost check** — median chat turn cost ≤ target ($0.03 Phase 1, $0.04 Phase 2, etc.).

If a phase doesn't pass its verification, the next phase doesn't start. We don't accumulate technical debt across phases.

---

## File-impact summary

By phase, which directories see the most change:

| Phase | Backend | Frontend | Tests |
|---|---|---|---|
| 1 — Power & Trust | `services/ai/tools_v2/*`, `services/codegen/{store,diff}.py`, `app.py` | `ChatPanel`, `RevisionTimeline`, parameter locks, slider live mode | `evals_v2/checks.py`, richer macro cases |
| 2 — Real Inputs | `services/codegen/runner/host.py`, `services/codegen/library/hardware/*`, `app.py` | `DesignStudio` file input, `SnippetSuggestions`, viewer raycast, manufacturability action | new STEP + hardware preset eval cases |
| 3 — Discovery | `services/codegen/gallery.py`, `data/gallery/*` | `app/(gallery)/`, `Onboarding/Tour` | gallery seed integrity |
| 4 — Power Inputs | `services/ai/tools_v2/read_image.py`, `agent_v2.py` | `ChatPanel` mic + image attach | image-prompt evals |
| 5 — Mfg Polish | `slicer_service.py`, `services/cam/*` | printer dropdown, compare view | print/mill smoke tests |
| 6 — Product | `app/middleware/{auth,quota}.py`, `app/api/billing.py` | `(billing)/`, `Header/UserMenu` | webhook round-trip |

---

## Time estimates *(solo dev, honest)*

| Phase | Est. weeks | Notes |
|---|---|---|
| Phase 0 | 0.5-1 | Just locking the 5 fixtures + integration smoke tests |
| Phase 1 | 2-3 | Macro tools + revision timeline + slider live mode + cost estimator + feature graph + locked params + richer evals |
| Phase 2 | 2-3 | STEP import is build123d round-trip work; export/make-printable are plumbing; mini-gallery and hardware presets are data; click-in-viewer needs Three.js raycast tagging |
| Phase 3 | 2-3 | Curating ~30-50 gallery designs is the time eater; tour + tooltips + responsive viewer are afternoon-tasks |
| Phase 4 | 2-3 | Vision API integration is straightforward; voice rewires mostly-done legacy code; the clarifying-question pattern needs prompt + eval work |
| Phase 5 | 3-4 | CNC handoff bundle (5.3a) is doable; cost/time estimator already in Phase 1; multi-printer profiles are config work; real CAM (5.3b) is **explicitly deferred** |
| Phase 6 | 4-5 | Auth + Stripe + quotas + sharing |
| **Headline total** | **16-22 wks** | ~4-5 months focused |
| **Realistic total** | **24-30 wks** | ~6 months with inevitable detours, debugging, support |

GPT was right to flag the original 15-19 number as optimistic; the realistic estimate adds ~50% buffer for unmodelled work. **MVP launchable in 6-8 weeks** (see [MVP cut](#mvp-cut) — much sooner than the full roadmap).

## MVP cut

If we have to ship something usable to non-developers fast — say, in 6-8 weeks — this is what makes it. Everything else is post-MVP.

**Must ship:**
- Phase 0 (flagship workflows + integration tests)
- Phase 1 (macro tools + revision timeline + sliders + cost estimator)
- Phase 2.4 (mini-gallery — 5 starter cards)
- Phase 2.2 (multi-process export — at minimum FDM preset)
- STL import (already done)
- Anonymous usage (already done)
- Visible cost per turn (already done)
- Tool-result confirmation lines (already done)
- Manufacturability check + repair (already done)

**Defer beyond MVP:**
- STEP import (Phase 2.1) — pulls in pro CAD users, but makers don't need it for the magic loop
- Click-in-viewer feature selection (Phase 2.5) — nice but not magic-loop critical
- Image / voice / sketch input (Phase 4)
- Full gallery (Phase 3.1) — 5 starter cards is enough for MVP
- CNC anything (Phase 5.3) — not magic-loop critical
- Multi-printer profiles (Phase 5.2) — single MK4 default is fine for MVP
- Auth / billing (Phase 6) — anonymous + free is enough to learn from users

**MVP success looks like:** a maker uploads "speaker grill 200mm" and 90 seconds later has a printable G-code file. They tweak ring count via a slider, see the cost change, hit Export, and print it. No login, no cost, no friction.

That's the loop GPT correctly identified as the magic. Everything else is amplification.

---

## Decision log

As the plan executes, decisions get logged here so future-us doesn't re-litigate.

### 2026-05-03 · MVP shipped — Phases 0/1/2.1/2.2/2.4/3.5

Single autonomous session. What landed:

- **Phase 0** — 5 flagship workflows (wall_hook, phone_stand, knob, bracket, enclosure) with parametric scripts + endpoint at `/design/flagship[/fork]` + 10/10 round-trip tests passing (build → mutate → re-build, mesh hash differs).
- **Phase 1.1** — 9 macro tools added to the agent: `mesh_subtract_primitive`, `mesh_add_primitive`, `mesh_offset_surface`, `mesh_split_at_plane`, `mesh_mirror`, `mesh_smooth`, `mesh_repair`, `detect_features` plus the existing `mesh_modify_holes`. Shared `_helpers.append_block_and_build` cuts each tool to ~80 lines. `manifold3d` and `shapely` added as deps. System prompt teaches the macro/script-edit hierarchy.
- **Phase 1.2** — Revision timeline endpoint (`/design/{id}/revisions`, `/design/{id}/revisions/restore`), per-revision script+build snapshots persisted (proper rewind, not just artifact promotion), UI strip above the viewer with thumbnails + ago timestamps + click-to-restore.
- **Phase 1.3** — `LIVE` toggle in the parameter header; debounced 250 ms re-renders on slider drag when on, on-commit only when off.
- **Phase 1.4** — Print cost / time estimator: parses `; estimated printing time` and `; filament used [g]` from PrusaSlicer headers; configurable `FILAMENT_PRICE_USD_PER_G` env var (default $0.025/g); inspector panel shows weight / time / cost in a 3-column grid.
- **Phase 1.5** — v2 eval suite at `tests/ai/evals_v2/` with 12 cases covering macro routing, parametric edits, ambiguity-clarifying behavior. Skip-if-no-API-key.
- **Phase 2.1** — STEP import (`.step`/`.stp`): runner pre-loads via `build123d.import_step` as `imported_part`; new `IMPORTED_STEP` seeder (build123d ops, not trimesh); preferred `/design/import-cad` upload endpoint with `/design/import-stl` as a compatibility alias. Honest framing: transform/augment is supported, full B-rep feature editing is not promised.
- **Phase 2.2** — Multi-process export presets (`POST /design/{id}/export?preset=fdm|cnc|docs|all`). CNC bundle includes auto-generated `setup_notes.json` with bbox, recommended stock, supported features, limitations, parameters-at-export. Frontend "Export ⌄" picker replaces the per-format buttons.
- **Phase 2.4** — Mini-gallery: 5 flagship cards on the empty state ("Wall hook · Phone stand · Cylindrical knob · Right-angle bracket · Electronics enclosure") via `/design/flagship/fork`. Closes the makers-vs-pros sequencing tension.
- **Phase 3.5** — Mobile-responsive: three columns collapse to one stack on <900 px viewports via injected `<style>` block.

What did NOT ship in this session (deferred per plan):

- 2.3 snippet starter cards — Claude routes snippets via `query_library` already; explicit UI cards are nice-to-have.
- 2.5 click-in-viewer feature selection — needs Three.js raycast tagging + per-feature mesh metadata; not magic-loop critical.
- 3.1–3.4 full gallery / tour / tooltips — empty state is rich enough for MVP; polish.
- Phase 4 — image / voice / sketch input.
- Phase 5 — CNC toolpath generation, multi-printer profiles, compare view.
- Phase 6 — auth / Stripe / sharing.

Verification:

- Backend tests: 10/10 flagship round-trip tests pass (`tests/flagship/`).
- Frontend: `npx tsc --noEmit` clean.
- Live preview: empty state renders with all five entry paths (prompt, chip, file import, flagship cards, primitive templates) on one screen with no scroll. Loading an existing design shows the revision timeline, parameter sliders + LIVE toggle, manufacturability panel, and a working `Export ⌄` menu.

Next session targets: 4.1 (image-to-design with clarifying-question pattern) or 5.3a (CNC handoff bundle PDF) or 3.1 (full gallery with curated designs). Leaving the choice to user direction.

### 2026-05-03 · GPT-5 review v2 — incorporated post-MVP cut

Most GPT-5 review points were already in the roadmap or shipped in the autonomous MVP session, including build123d core, macro tools, revision timeline, STEP import, multi-process export, mini-gallery, mobile-responsive viewer, CNC handoff split, manufacturability panel, mesh utility tools, and `/route-intent`.

The remaining gaps are now folded in:

- **Phase 1 gains** — feature graph v1 (1.6), cost-tier badges consuming the shipped router (1.7), structured selected-feature context replacing the inline-tag hack (1.8), revision diff summary (1.9), locked parameters (1.10), and geometry-property eval checks (1.11).
- **Phase 2 gains** — hardware vocabulary library (2.6) and one-click Make printable bundle (2.7).
- **Did not adopt** — "CAD compiler" rebrand, OpenCascade.js as the primary engine, a top-level B-rep/mesh split, a separate structured-action JSON layer, or a separate intent-router phase.

Rationale: the feature graph is the keystone. Once features have stable IDs and parents, click-selection, selected-feature chat context, revision diff, and gallery forks stop depending on string matching. Hardware vocabulary is a data-only addition that unlocks manufacturing-intent language. Make printable assembles existing repair, orient, scan, and export pieces into the maker-facing product moment.

### 2026-05-03 · Roadmap v2 — incorporated GPT review

- **Added Phase 0** (flagship workflows) as integration test rail. Locks 5 designs as the survives-every-refactor anchor.
- **Print cost / time estimator moved to Phase 1** (was Phase 5). Low effort, high trust value, the data is free from PrusaSlicer.
- **STEP capability tiered** (inspect / transform / augment / edit) instead of "edit any STEP." Honest framing that pro users can verify. Underpromise, overdeliver.
- **CNC split into 5.3a (handoff bundle, achievable) and 5.3b (real CAM, deferred to Phase 7+).** Real CAM is multi-month and dangerous to fake; the handoff bundle is honest and useful today.
- **Image-to-design framed as "rough starting point" with clarifying-question pattern.** Single-image inverse CAD is unreliable; we own that limitation in the UX.
- **Mini-gallery (5 cards) added to Phase 2** alongside STEP import. Closes the makers vs pros sequencing tension GPT flagged.
- **Time estimate updated to 24-30 weeks realistic** (was 15-19 best-case). Headline number stays 16-22 weeks; reality is ~6 months.
- **MVP cut explicitly defined** at 6-8 weeks with a stripped-down feature list. Lets us ship and learn before the full roadmap is done.
- **Positioning section added** with three taglines (maker / user / investor). Reinforces "AI-first parametric CAD" category vs traditional CAD.
- **The magic loop made explicit** at the top: *Describe → See → Edit → Undo → Export.* Every feature must serve this loop or it doesn't ship.
- **Did not adopt** GPT's suggestion to rebrand "chat" in the UI. Keeping "Chat with Pulsai" header (already user-tested) but the input placeholder remains "Describe an edit…" — best of both. "Refine" / "Ask Pulsai" stays as a vocabulary note in [Phase 4](#phase-4--power-inputs-weeks-810) for buttons in image/voice contexts where "chat" is ambiguous.
