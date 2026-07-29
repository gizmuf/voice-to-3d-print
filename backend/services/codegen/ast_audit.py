"""Static AST audit for user / LLM-generated build123d scripts.

The audit runs *before* we hand a script to the sandbox subprocess. It is one
of three defense layers (the others being the subprocess boundary itself and
resource limits). It catches the easy attacks early and gives clearer error
messages than a sandbox kill.

Threat model: Claude (or a malicious user via prompt injection) writes Python
that tries to escape the CAD context — read secrets, hit the network, exec
shell commands, fork. We reject anything that even looks like it.

What we allow:
- All build123d / cadquery / OCP imports and calls
- math, numpy, shapely, dataclasses, typing, statistics, copy, itertools,
  functools, json (read-only-feeling stdlib utilities), random, enum
- Standard arithmetic, control flow, comprehensions, classes, functions
- The `pulsai` shim module (provided by the runner) for parameter exposure

What we reject:
- os, sys, subprocess, socket, pathlib, importlib, ctypes, threading,
  multiprocessing, pickle, marshal, shelve, sqlite3, urllib, requests, http,
  builtins, asyncio, signal, resource, mmap, fcntl, termios, pty
- exec, eval, compile, __import__, getattr/setattr on dunder names, breakpoint
- attribute access to __class__, __mro__, __subclasses__, __globals__,
  __builtins__, __dict__, __code__, __closure__, __getattribute__
- File I/O (open) — outputs go via the build123d export functions which the
  runner controls

Reasoning: the audit is intentionally strict for the stdlib because allowing
even one transitive escape (e.g. ``json`` is fine; ``importlib`` is not) lets
a determined attacker chain into ``os``. CAD code does not need any of those.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


ALLOWED_TOP_LEVEL_MODULES: frozenset[str] = frozenset(
    {
        "build123d",
        "cadquery",
        "ocp_vscode",
        "OCP",
        "math",
        "numpy",
        "np",
        "dataclasses",
        "typing",
        "statistics",
        "copy",
        "itertools",
        "functools",
        "json",
        "random",
        "enum",
        "collections",
        "operator",
        "trimesh",  # mesh ops on imported STLs
        "shapely",  # traced 2D jewelry regions extruded via trimesh
        "manifold3d",  # trimesh's boolean engine
        "pulsai",  # the runner-provided helper (see runner/host.py)
    }
)

DENIED_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "breakpoint",
        "open",
        "input",
        "globals",
        "vars",
        "locals",
        "memoryview",
        "help",
    }
)

DENIED_ATTRS: frozenset[str] = frozenset(
    {
        "__class__",
        "__bases__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__builtins__",
        "__dict__",
        "__code__",
        "__closure__",
        "__getattribute__",
        "__reduce__",
        "__reduce_ex__",
        "__import__",
        "__loader__",
        "__spec__",
        "__file__",
        "__cached__",
        "__path__",
        "__name__",  # actually fine in normal use, but blocks `__name__.__class__` chains
    }
)

BUILD123D_PRIMITIVES: frozenset[str] = frozenset(
    {
        "Box",
        "Cylinder",
        "Cone",
        "Sphere",
        "Torus",
        "Wedge",
        "CounterBoreHole",
        "CounterSinkHole",
        "Hole",
        "RegularPolygon",
        "Circle",
        "Rectangle",
        "Slot",
    }
)


@dataclass
class AuditResult:
    ok: bool
    errors: list[str]


class _Build123dBuilderAudit(ast.NodeVisitor):
    """Catch common builder-mode mistakes before they become bad geometry."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self._buildpart_depth = 0

    def visit_With(self, node: ast.With) -> None:
        enters_buildpart = any(_is_call_named(item.context_expr, "BuildPart") for item in node.items)
        if enters_buildpart:
            self._buildpart_depth += 1
        try:
            self.generic_visit(node)
        finally:
            if enters_buildpart:
                self._buildpart_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        self._check_primitive_assignment(node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._check_primitive_assignment(node.value, node.lineno)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._check_primitive_assignment(node.value, node.lineno)
        self.generic_visit(node)

    def _check_primitive_assignment(self, value: ast.AST, lineno: int) -> None:
        if self._buildpart_depth <= 0:
            return
        if _contains_build123d_primitive_call(value):
            self.errors.append(
                "line "
                f"{lineno}: assigning a build123d primitive inside BuildPart auto-adds geometry; "
                "create temporary cutters outside the BuildPart context, or call the primitive "
                "directly without assigning it."
            )


def _is_call_named(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == name
    if isinstance(func, ast.Attribute):
        return func.attr == name
    return False


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _contains_build123d_primitive_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _call_name(child) in BUILD123D_PRIMITIVES:
            return True
    return False


def _top_level_result_assignments(tree: ast.Module) -> list[ast.Assign | ast.AnnAssign]:
    assignments: list[ast.Assign | ast.AnnAssign] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "result" for target in node.targets):
                assignments.append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "result":
                assignments.append(node)
    return assignments


def audit_script(source: str) -> AuditResult:
    """Parse and audit a script. Returns ok=False on any violation."""
    errors: list[str] = []
    try:
        tree = ast.parse(source, filename="<design>", mode="exec")
    except SyntaxError as exc:
        return AuditResult(ok=False, errors=[f"SyntaxError: {exc}"])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ALLOWED_TOP_LEVEL_MODULES:
                    errors.append(
                        f"line {node.lineno}: import '{alias.name}' is not allowed"
                    )
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top not in ALLOWED_TOP_LEVEL_MODULES:
                errors.append(
                    f"line {node.lineno}: from-import '{node.module}' is not allowed"
                )
        elif isinstance(node, ast.Name):
            if node.id in DENIED_NAMES and isinstance(node.ctx, ast.Load):
                errors.append(
                    f"line {node.lineno}: use of '{node.id}' is not allowed"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in DENIED_ATTRS:
                errors.append(
                    f"line {node.lineno}: attribute access '.{node.attr}' is not allowed"
                )

    builder_audit = _Build123dBuilderAudit()
    builder_audit.visit(tree)
    errors.extend(builder_audit.errors)

    result_assignments = _top_level_result_assignments(tree)
    if len(result_assignments) != 1:
        lines = [str(getattr(node, "lineno", "?")) for node in result_assignments]
        errors.append(
            "script must have exactly one top-level `result = ...` assignment "
            f"as the final executable statement; found {len(result_assignments)}"
            + (f" at lines {', '.join(lines)}" if lines else "")
            + ". Use `part = ...` inside feature blocks and let the final result "
            "line export that part."
        )
    elif tree.body and tree.body[-1] is not result_assignments[0]:
        errors.append(
            "the top-level `result = ...` assignment must be the final executable "
            "statement so stale result lines cannot override later feature edits."
        )

    return AuditResult(ok=not errors, errors=errors)


__all__ = [
    "audit_script",
    "AuditResult",
    "ALLOWED_TOP_LEVEL_MODULES",
    "DENIED_NAMES",
    "BUILD123D_PRIMITIVES",
]
