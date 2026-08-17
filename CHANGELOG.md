# Changelog

Notable public changes to Pulsai 3D are recorded here.

## [Unreleased]

### Fixed

- Keep the latest successful CAD revision visible after chat or local edits
  instead of snapping the preview and sliders back to the first version.
- Download export bundles and STL/GLB/STEP files through the signed-in session
  instead of opening a raw unauthenticated artifact tab.
- Rewrite the non-coder tester guide so it matches the live hosted flow.

## [0.1.0] - 2026-08-17

### Added

- Public AGPL-3.0-or-later source release with security and contribution docs.
- Parametric build123d/OpenCascade Design Studio with starter models,
  revisions, deterministic edits, and optional provider-backed chat.
- STEP/STP and STL import paths plus STEP, STL, GLB, DXF, bundle, and optional
  FDM G-code exports.
- FDM/CNC manufacturability heuristics, printer profiles, and PrusaSlicer
  integration.
- Owner-scoped authentication, private artifacts, BYOK provider routing,
  secret scanning, and public-safe defaults.
- Linux CI covering backend, frontend, STT, security, and a free browser
  CAD-to-print flow.

### Known limitations

- This is an alpha release and is not safety-certified for manufacturing.
- Imported STEP feature trees and arbitrary STL meshes are not fully
  reconstructable in every case.
- AI and organic-mesh results vary by provider and may require a customer-owned
  paid account.
- Every exported model, printer profile, and G-code file requires independent
  review.

[Unreleased]: https://github.com/gizmuf/voice-to-3d-print/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/gizmuf/voice-to-3d-print/releases/tag/v0.1.0
