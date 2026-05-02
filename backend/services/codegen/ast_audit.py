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
- math, numpy, dataclasses, typing, statistics, copy, itertools, functools,
  json (read-only-feeling stdlib utilities), random, enum
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


@dataclass
class AuditResult:
    ok: bool
    errors: list[str]


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

    return AuditResult(ok=not errors, errors=errors)


__all__ = ["audit_script", "AuditResult", "ALLOWED_TOP_LEVEL_MODULES", "DENIED_NAMES"]
