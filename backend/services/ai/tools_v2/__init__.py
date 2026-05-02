"""Powerful AI tool set for the code-driven Pulsai engine.

Six tools that together let Claude do real CAD work:

- ``read_design``         — get the current script + parameters + last build summary.
- ``query_library``       — search the build123d snippet library.
- ``update_parameter``    — fast path: re-run the script with a new parameter value.
- ``replace_feature``     — surgical: swap the body of a named ``# @feature: name`` block.
- ``append_feature``      — additive: append a new feature block to the script.
- ``rewrite_design``      — full replacement when surgery isn't enough.
- ``run_build``           — produce STL/STEP/DXF/GLB and (optionally) G-code.
- ``check_manufacturability`` — process-aware (fdm | cnc) report.

There is no capability matrix and no per-template gating. Refusals come from
the AST audit (security only) and from the sandbox (real CAD errors). If the
model wants to make triangular holes, it can — it just edits the right
feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from services.codegen.models import Build, Design


@dataclass
class DesignContext:
    """Mutable per-turn context shared across tool calls."""

    design_id: str
    design: Design
    output_dir: Path
    printer_profile_id: str
    last_build: Build | None = None

    def reload(self, design: Design) -> None:
        self.design = design


from services.ai.tools_v2 import (  # noqa: E402  -- after dataclass declaration
    append_feature as _append_feature,
    check_manufacturability as _check_manufacturability,
    detect_features as _detect_features,
    mesh_add_primitive as _mesh_add_primitive,
    mesh_mirror as _mesh_mirror,
    mesh_modify_holes as _mesh_modify_holes,
    mesh_offset_surface as _mesh_offset_surface,
    mesh_repair as _mesh_repair,
    mesh_smooth as _mesh_smooth,
    mesh_split_at_plane as _mesh_split_at_plane,
    mesh_subtract_primitive as _mesh_subtract_primitive,
    query_library as _query_library,
    read_design as _read_design,
    replace_feature as _replace_feature,
    rewrite_design as _rewrite_design,
    run_build as _run_build,
    update_parameter as _update_parameter,
)


_MODULES = [
    # diagnostics
    _read_design,
    _query_library,
    _detect_features,
    # parametric path
    _update_parameter,
    _replace_feature,
    _append_feature,
    # mesh-level macro tools (cheap, common operations)
    _mesh_modify_holes,
    _mesh_subtract_primitive,
    _mesh_add_primitive,
    _mesh_offset_surface,
    _mesh_split_at_plane,
    _mesh_mirror,
    _mesh_smooth,
    _mesh_repair,
    # escape hatch
    _rewrite_design,
    # building & validation
    _run_build,
    _check_manufacturability,
]


TOOL_DEFINITIONS: list[dict[str, Any]] = [m.TOOL_DEFINITION for m in _MODULES]
TOOL_DISPATCH: dict[str, Callable[[dict, "DesignContext"], dict]] = {
    m.TOOL_DEFINITION["name"]: m.execute for m in _MODULES
}


def execute(name: str, payload: dict, ctx: "DesignContext") -> dict:
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return handler(payload, ctx)
    except Exception as exc:
        return {"error": f"Tool {name} raised: {exc}"}


__all__ = ["DesignContext", "TOOL_DEFINITIONS", "TOOL_DISPATCH", "execute"]
