"""Pulsai code-driven CAD engine.

The Design is a build123d Python script. Editing = rewriting (or surgically
patching) the script. The script is the source of truth; everything else
(named features, parameters, manufacturability) is derived from running it.

Manufacturability has exactly one supported implementation: the profile-aware,
process-aware pipeline in :mod:`services.codegen.engine`. Do not add a parallel
checker under ``services/``; compatibility entry points should delegate to the
canonical engine instead of duplicating thresholds, sampling or status logic.
"""
