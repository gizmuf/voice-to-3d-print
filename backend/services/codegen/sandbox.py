"""Spawn the runner subprocess with a minimal environment.

This is the only place in the backend that calls ``subprocess.Popen``. The
sandbox layer is intentionally small: AST audit happens before we get here,
resource limits happen inside the subprocess (services/codegen/runner/host.py),
and our job here is to (a) wall-clock-bound the subprocess, (b) strip the
environment so secrets never reach user code, and (c) collect ``result.json``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from config import settings


WALL_CLOCK_TIMEOUT_S = 120.0


SAFE_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        # Build123d / OCP wants HOME for one cache directory. We fake one inside the workdir.
    }
)


@dataclass
class SandboxResult:
    ok: bool
    payload: dict
    stderr: str
    stdout: str
    timed_out: bool
    return_code: int


def _runner_command() -> list[str]:
    """Resolve the python interpreter + the runner host module."""
    interpreter = sys.executable
    here = Path(__file__).resolve().parent / "runner" / "host.py"
    return [interpreter, "-I", str(here)]


def _build_env(workdir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
    env["HOME"] = str(workdir)
    env["TMPDIR"] = str(workdir)
    # Forbid color codes and stop OCP from probing weird paths.
    env["NO_COLOR"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    # Pulsai never wants the user script to phone home — none of the heavy
    # client libs read these unless we set them, but the strip is belt-and-braces.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    return env


def run_design(
    *,
    script: str,
    parameter_overrides: dict | None = None,
    targets: list[str] | None = None,
    workspace_dir: Path | None = None,
    job_id: str | None = None,
    wall_clock_timeout_s: float = WALL_CLOCK_TIMEOUT_S,
    imported_files: dict[str, str] | None = None,
) -> SandboxResult:
    """Run a design script in an isolated subprocess and return the result."""
    job_id = job_id or uuid.uuid4().hex
    base = workspace_dir or settings.output_dir / "designs" / job_id
    base.mkdir(parents=True, exist_ok=True)

    job_payload = {
        "script": script,
        "parameter_overrides": parameter_overrides or {},
        "targets": targets or ["stl", "step", "glb"],
        "imported_files": imported_files or {},
    }
    (base / "job.json").write_text(json.dumps(job_payload))

    cmd = _runner_command() + [str(base)]
    env = _build_env(base)

    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(base),
            env=env,
            capture_output=True,
            text=True,
            timeout=wall_clock_timeout_s,
            check=False,
        )
        return_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = -1
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")

    duration_ms = int((time.perf_counter() - started) * 1000)
    result_path = base / "result.json"
    payload: dict = {}
    if result_path.exists():
        try:
            payload = json.loads(result_path.read_text())
        except Exception as exc:
            payload = {"ok": False, "error": f"cannot parse runner result.json: {exc}"}

    if not payload:
        payload = {
            "ok": False,
            "error": (
                "Runner did not produce result.json — likely killed by the OS or "
                "blocked at import time."
            ),
        }

    payload.setdefault("duration_ms", duration_ms)
    if timed_out:
        payload["ok"] = False
        payload["error"] = (
            f"Sandbox subprocess exceeded {wall_clock_timeout_s:.0f}s wall clock; killed."
        )

    return SandboxResult(
        ok=bool(payload.get("ok")),
        payload=payload,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        return_code=return_code,
    )


__all__ = ["run_design", "SandboxResult", "WALL_CLOCK_TIMEOUT_S"]
