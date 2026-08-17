# Changelog

Notable public changes to Pulsai 3D are recorded here.

## [Unreleased]

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
