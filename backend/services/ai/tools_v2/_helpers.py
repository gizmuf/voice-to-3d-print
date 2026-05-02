"""Shared helpers for macro tools that all follow the same shape:

1. Validate input (Pydantic).
2. Append a ``# @feature: <name>`` block to the script.
3. Sandbox-build the new script with imported_files + parameter overrides.
4. On success, persist the new revision; on failure, return the sandbox error.

Centralising this keeps each macro tool small (input model + block template
+ a few lines of glue) and ensures every macro respects the same trust
contracts (revision-id update, imported-mesh passthrough, audit fail handling).
"""

from __future__ import annotations

from typing import Any

from services.ai.tools_v2 import DesignContext
from services.codegen.engine import (
    audit_then_run,
    derive_named_features,
    derive_parameters,
)
from services.codegen.store import new_revision_id, save_design


def append_block_and_build(
    ctx: DesignContext,
    *,
    feature_name: str,
    block: str,
    extra_result_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a feature block to the current script, build, persist, return.

    The block must be plain build123d / trimesh code; the caller wraps it
    with ``# @feature: <name>`` ... ``# @end`` markers automatically.
    """
    if any(f.name == feature_name for f in ctx.design.features):
        return {
            "error": (
                f"Feature '{feature_name}' already exists. Use replace_feature "
                "if you mean to modify it."
            )
        }

    full_block = (
        f"\n# @feature: {feature_name}\n"
        f"{block.rstrip()}\n"
        "# @end\n"
    )

    # Insert just before the final `result = ...` so the block participates
    # in the assignment.
    lines = ctx.design.script.splitlines()
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("result"):
            insert_idx = i
            break
    new_script = "\n".join(lines[:insert_idx] + [full_block] + lines[insert_idx:])

    overrides = {p.name: p.value for p in ctx.design.parameters}
    sandbox_result = audit_then_run(
        script=new_script,
        parameter_overrides=overrides,
        targets=["stl"],
        imported_files=ctx.design.metadata.get("imported_files") or None,
    )
    if not sandbox_result.ok:
        return {
            "error": (
                f"{feature_name} build failed; design unchanged. "
                f"Sandbox said: {sandbox_result.payload.get('error')}"
            ),
            "traceback": (sandbox_result.payload.get("traceback") or "")[:600],
        }

    previous_features = list(ctx.design.features)
    ctx.design.parent_revision_id = ctx.design.revision_id
    ctx.design.revision_id = new_revision_id()
    ctx.design.script = new_script
    ctx.design.parameters = derive_parameters(sandbox_result.payload)
    ctx.design.features = derive_named_features(
        sandbox_result.payload,
        new_script,
        previous_features=previous_features,
        revision_id=ctx.design.revision_id,
        created_by="macro",
        source_prompt=ctx.current_user_message,
    )
    save_design(ctx.design)
    out: dict[str, Any] = {
        "ok": True,
        "feature_name": feature_name,
        "new_revision_id": ctx.design.revision_id,
        "feature_count": len(ctx.design.features),
    }
    if extra_result_payload:
        out.update(extra_result_payload)
    return out


def require_imported_mesh(ctx: DesignContext, tool_name: str) -> dict[str, Any] | None:
    """Some macros only make sense on an imported-STL design. Returns an error
    dict if the precondition is not met; ``None`` otherwise.
    """
    if not ctx.design.metadata.get("imported_files"):
        return {
            "error": (
                f"{tool_name} only operates on designs seeded from an STL "
                "upload (where `mesh` / `imported_mesh` is in scope). The "
                "current design is parametric — use the equivalent build123d "
                "primitive instead."
            )
        }
    return None


__all__ = ["append_block_and_build", "require_imported_mesh"]
