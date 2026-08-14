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
import selectors
import signal
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


def _positive_limit(value: int | None, default: int) -> int:
    """Return a usable byte limit without allowing zero/negative disablement."""
    candidate = default if value is None else int(value)
    return candidate if candidate > 0 else default


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


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_bounded(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float,
    output_limit: int,
) -> tuple[int, str, str, bool, bool]:
    """Run a child while bounding combined stdout/stderr and all descendants."""
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None and process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout_s
    timed_out = False
    output_limited = False

    while process.poll() is None or selector.get_map():
        if process.poll() is None and time.monotonic() >= deadline:
            timed_out = True
            _kill_process_group(process)
        events = selector.select(timeout=0.1) if selector.get_map() else []
        for key, _ in events:
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            remaining = output_limit - sum(len(value) for value in buffers.values())
            if remaining <= 0 or len(chunk) > remaining:
                output_limited = True
                if remaining > 0:
                    buffers[key.data].extend(chunk[:remaining])
                _kill_process_group(process)
            else:
                buffers[key.data].extend(chunk)
        if process.poll() is not None and not events:
            for fileobj in list(selector.get_map().values()):
                try:
                    selector.unregister(fileobj.fileobj)
                except Exception:
                    pass

    try:
        return_code = process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process_group(process)
        return_code = process.wait(timeout=1.0)
    return (
        return_code,
        buffers["stdout"].decode("utf-8", "replace"),
        buffers["stderr"].decode("utf-8", "replace"),
        timed_out,
        output_limited,
    )


def run_design(
    *,
    script: str,
    parameter_overrides: dict | None = None,
    targets: list[str] | None = None,
    workspace_dir: Path | None = None,
    job_id: str | None = None,
    wall_clock_timeout_s: float = WALL_CLOCK_TIMEOUT_S,
    imported_files: dict[str, str] | None = None,
    artifact_file_limit_bytes: int | None = None,
    artifact_total_limit_bytes: int | None = None,
) -> SandboxResult:
    """Run a design script in an isolated subprocess and return the result."""
    job_id = job_id or uuid.uuid4().hex
    base = workspace_dir or settings.output_dir / "designs" / job_id
    base.mkdir(parents=True, exist_ok=True)

    file_limit = _positive_limit(
        artifact_file_limit_bytes,
        settings.max_cad_artifact_bytes,
    )
    total_limit = _positive_limit(
        artifact_total_limit_bytes,
        settings.max_cad_artifact_total_bytes,
    )

    job_payload = {
        "script": script,
        "parameter_overrides": parameter_overrides or {},
        "targets": targets or ["stl", "step", "glb"],
        "imported_files": imported_files or {},
        "artifact_limits": {
            "per_file_bytes": file_limit,
            "aggregate_bytes": total_limit,
        },
    }
    # Never allow a killed or failed child to inherit an earlier success result
    # from a reused workspace.
    (base / "result.json").unlink(missing_ok=True)
    (base / "job.json").write_text(json.dumps(job_payload))

    # Pass the per-file limit on argv so the runner can install RLIMIT_FSIZE
    # before importing CAD libraries or reading attacker-influenced source.
    cmd = _runner_command() + [str(base), str(file_limit)]
    env = _build_env(base)

    started = time.perf_counter()
    return_code, stdout, stderr, timed_out, output_limited = _run_bounded(
        cmd,
        cwd=base,
        env=env,
        timeout_s=wall_clock_timeout_s,
        output_limit=settings.max_subprocess_output_bytes,
    )

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
    if output_limited:
        payload["ok"] = False
        payload["error"] = "Sandbox subprocess exceeded the output limit; killed."

    return SandboxResult(
        ok=bool(payload.get("ok")),
        payload=payload,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        return_code=return_code,
    )


__all__ = ["run_design", "SandboxResult", "WALL_CLOCK_TIMEOUT_S"]
