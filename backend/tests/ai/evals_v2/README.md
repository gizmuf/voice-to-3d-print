# Pulsai CAD quality benchmark

The catalog contains exactly 30 maker tasks across parametric parts, imported
STL operations, ambiguity handling, Polish/English requests, precision fits,
and multi-parameter edits.

- The free lane validates the catalog schema and all deterministic local edits.
- The live lane runs the same tasks against a deployed or local backend when
  `ANTHROPIC_API_KEY` is present.
- A case passes only when the requested tool succeeds, required geometry checks
  pass, destructive ambiguity is avoided, and token ceilings are respected.
- Cases marked `expected_model: local` must use zero model tokens and emit a
  deterministic compliance report when the prompt contains absolute values.

This benchmark measures repeatable product behavior. It is not engineering
certification and does not replace human review for load-bearing parts.
