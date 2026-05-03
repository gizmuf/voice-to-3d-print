"""Tool-call telemetry: append-only JSONL log for production signal.

Eval cases catch regressions in CI. This module fills the production gap:
every tool call writes one line with success/failure, duration, and tool
name to ``data/telemetry/tool_calls.jsonl``. The admin endpoint summarizes.

Best-effort by design — telemetry must never block a chat turn or raise.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from config import settings


def _telemetry_path(*, create: bool = False) -> Path:
    path = settings.output_dir.parent / "telemetry" / "tool_calls.jsonl"
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_tool_call(
    *,
    tool_name: str,
    success: bool,
    duration_ms: int,
    design_id: str | None = None,
) -> None:
    """Append one tool-call record. Silently swallows IO errors."""
    payload = {
        "tool_name": tool_name,
        "success": success,
        "duration_ms": duration_ms,
        "design_id": design_id,
        "ts": time.time(),
    }
    try:
        path = _telemetry_path(create=True)
        with path.open("a") as fh:
            fh.write(json.dumps(payload) + "\n")
    except Exception:
        # Telemetry is best-effort. We never want to fail a chat turn here.
        pass


def summarize_tool_calls(*, limit: int = 5_000) -> dict[str, Any]:
    """Aggregate the last `limit` records into per-tool counters."""
    path = _telemetry_path()
    if not path.exists():
        return {"records": 0, "tools": {}}

    lines: list[str] = []
    try:
        with path.open() as fh:
            lines = fh.readlines()
    except Exception:
        return {"records": 0, "tools": {}}

    if limit and len(lines) > limit:
        lines = lines[-limit:]

    successes: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    duration_total: dict[str, int] = {}
    duration_count: dict[str, int] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        name = row.get("tool_name")
        if not isinstance(name, str):
            continue
        if row.get("success"):
            successes[name] += 1
        else:
            failures[name] += 1
        ms = row.get("duration_ms")
        if isinstance(ms, (int, float)):
            duration_total[name] = duration_total.get(name, 0) + int(ms)
            duration_count[name] = duration_count.get(name, 0) + 1

    tools: dict[str, dict[str, Any]] = {}
    for name in set(successes) | set(failures):
        ok = successes[name]
        bad = failures[name]
        avg_ms = (
            duration_total[name] // duration_count[name]
            if duration_count.get(name)
            else 0
        )
        tools[name] = {
            "success": ok,
            "failure": bad,
            "success_rate": round(ok / (ok + bad), 3) if (ok + bad) else 0.0,
            "avg_duration_ms": avg_ms,
        }
    return {"records": len(lines), "tools": tools}


__all__ = ["record_tool_call", "summarize_tool_calls"]
