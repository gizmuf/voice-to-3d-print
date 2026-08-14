# CAD product capability plan

This plan separates engineering goals from claims already supported by tests.
Passing one benchmark is not universal CAD, manufacturing, motion, or CAM
validation.

## 1. Stable viewer-to-CAD selection

Current raycasts identify a rendered triangle and then use point/name
heuristics. That is enough for focus markers but not for reliably editing “this
exact hole” after a rebuild.

Target contract:

1. Every named CAD feature receives an immutable `feature_id`.
2. The build emits a `selection_map.json` containing B-rep face lineage,
   surface type, area, centroid, adjacency signature, and generated GLB
   primitive/group identifiers.
3. GLB primitive `extras` carry `feature_id` and `topology_ref`; viewer raycasts
   return those identifiers rather than a raw triangle index.
4. A rebuild matches faces first through operation lineage and then through a
   geometric signature. Ambiguous matches expose confidence and ask the user to
   confirm instead of silently editing another feature.
5. Regression fixtures select one of several similar holes, edit only it,
   rebuild, and verify feature identity, geometry hash, artifacts, and preview.

Benefit: precise click-to-edit, stable issue markers, meaningful revision diffs,
and fewer dangerous edits to the wrong repeated feature.

## 2. STEP and STL imports

Losing original feature history is real when a user expects dimensions and
features from the authoring CAD system. It is not data that can be recovered
reliably from STEP or STL after export.

- STEP remains preferred: preserve the exact B-rep as an immutable imported
  base and add Pulsai-owned parametric operations above it.
- Add confidence-scored feature recognition for cylinders/holes, pockets,
  fillets, planar profiles, and repeated patterns. Label it “recognized”, never
  “original history”.
- STL defaults to mesh repair, split, transform, boolean, and reference use.
  Reconstruct parametric primitives only when fit residual and topology checks
  pass; otherwise ask for STEP or native source.
- Preserve the uploaded original and make every reconstruction reversible.

## 3. Image-to-parametric CAD

The main chat now accepts a JPEG/PNG/WebP/GIF reference for an Anthropic BYOK
turn, and image bytes are not persisted in conversation history. The image is a
visual constraint, not metrology.

Next acceptance gate:

- require one real-world anchor dimension when scale cannot be inferred;
- extract a versioned constraint sketch with confidence and user-editable
  contour roles;
- build parametric CAD from the approved sketch, not directly from pixels;
- show image/sketch/CAD overlay and dimensional residuals;
- benchmark orthographic drawings, hand sketches, single photos, and ambiguous
  multi-view references separately.

Do not claim that one photo yields an accurate arbitrary STEP model.

## 4. Prepare to print

The current hard gate blocks G-code for non-watertight or over-bed models and a
known-safe browser flow produces STL/G-code/ZIP. Overhang warnings can be sent
to PrusaSlicer with supports. Automatic repair and application of the suggested
orientation are not yet universal.

Required production pipeline:

1. Preserve the CAD source and original STL.
2. Run deterministic mesh cleanup in a derived print revision; record every
   repair and before/after mesh hash.
3. Search candidate orientations against overhang, support volume, bed contact,
   height, strength direction, and user-declared cosmetic/functional faces.
4. Re-run watertightness, winding, wall, clearance, bed, and profile checks on
   the prepared derivative.
5. Slice only the exact verified derivative and bind G-code to its hash,
   printer/nozzle/material profile, slicer version, and settings.
6. Add golden parts, deliberately broken meshes, slicer-open checks, and a real
   printer matrix. Never describe heuristic printability as a safety guarantee.

## 5. Motion and strength

Implement capability tiers rather than one vague “simulation” label:

- Tier A: kinematic joints, travel limits, interference, swept-volume collision,
  and clearances. This is the next useful maker feature and is CPU-friendly.
- Tier B: rigid-body dynamics for mechanisms with explicit mass, joints, and
  loads; results remain idealized.
- Tier C: FEA through a validated solver worker, with explicit material,
  anisotropy, infill, boundary conditions, mesh convergence, and safety factor.

Printed-part strength must remain an engineering estimate until material,
printer, orientation, process, and physical tests are known.

## 6. CNC / CAM

**Priority decision (August 2026): deferred.** Keep the honest STEP/DXF/setup
handoff, but do not invest in CAM/toolpath expansion until the FDM design,
make-printable, slicing, and real-printer validation loop is dependable.

A reliable first product is scoped 2.5D and simple 3-axis CAM, not universal
CNC. Require machine envelope, controller/postprocessor, stock, work offset,
fixture, tools, material, feeds/speeds, and operation strategy. Generate
toolpaths, simulate stock removal, check holder/fixture collisions and travel,
then postprocess. Release a machine/post pair only after simulator checks,
air-cut/dry-run, and measured sample parts. Until then STEP/DXF/setup notes are
correctly labeled as a CAM handoff.

## 7. GPU boundary

build123d/OpenCascade, CadQuery, mesh inspection, stable topology, slicing,
kinematics, and ordinary 2.5D CAM are CPU workloads. GPU workers are optional
for local image/mesh generation and may help heavy simulation. Keep them
separate from the core VPS runtime and scale them only when benchmarks justify
the cost.
