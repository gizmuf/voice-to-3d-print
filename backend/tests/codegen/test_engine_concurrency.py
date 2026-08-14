from __future__ import annotations

import multiprocessing
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import pytest
from services.codegen import engine
from services.codegen.models import Build, Design
from services.codegen.sandbox import SandboxResult


def _design(design_id: str) -> Design:
    return Design(
        id=design_id,
        revision_id="b" * 32,
        name="Concurrency test",
        script="result = Box(1, 1, 1)",
    )


def _sandbox_result() -> SandboxResult:
    return SandboxResult(
        ok=True,
        payload={"mesh_hash": "test-hash", "artifacts": {}},
        stderr="",
        stdout="",
        timed_out=False,
        return_code=0,
    )


def _build_result(design: Design) -> Build:
    return Build(revision_id=design.revision_id, mesh_hash="test-hash")


def _process_build_worker(
    output_dir: str,
    design_id: str,
    entered,
    release,
    completed,
) -> None:
    """Exercise build_design in an independent Linux worker process."""
    object.__setattr__(config.settings, "output_dir", Path(output_dir))

    def fake_audit_then_run(**_kwargs) -> SandboxResult:
        entered.put(os.getpid())
        if not release.wait(timeout=5):
            raise TimeoutError("process build test was not released")
        return _sandbox_result()

    def fake_build_from_sandbox_result(design: Design, *_args, **_kwargs) -> Build:
        return _build_result(design)

    engine.audit_then_run = fake_audit_then_run
    engine.build_from_sandbox_result = fake_build_from_sandbox_result
    try:
        engine.build_design(_design(design_id))
    except BaseException as exc:
        completed.put((os.getpid(), type(exc).__name__, str(exc)))
        return
    completed.put((os.getpid(), "ok", ""))


def test_same_design_builds_serialize_complete_thread_critical_section(
    tmp_path: Path,
    monkeypatch,
) -> None:
    object.__setattr__(config.settings, "output_dir", tmp_path)
    first_finalizing = threading.Event()
    release_first = threading.Event()
    second_audit_entered = threading.Event()
    calls_guard = threading.Lock()
    audit_calls = 0
    finalize_calls = 0

    def fake_audit_then_run(**_kwargs) -> SandboxResult:
        nonlocal audit_calls
        with calls_guard:
            audit_calls += 1
            if audit_calls == 2:
                second_audit_entered.set()
        return _sandbox_result()

    def fake_build_from_sandbox_result(design: Design, *_args, **_kwargs) -> Build:
        nonlocal finalize_calls
        with calls_guard:
            finalize_calls += 1
            is_first = finalize_calls == 1
        if is_first:
            first_finalizing.set()
            assert release_first.wait(timeout=5)
        return _build_result(design)

    monkeypatch.setattr(engine, "audit_then_run", fake_audit_then_run)
    monkeypatch.setattr(engine, "build_from_sandbox_result", fake_build_from_sandbox_result)
    design = _design("a" * 32)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(engine.build_design, design)
        assert first_finalizing.wait(timeout=2)
        second = pool.submit(engine.build_design, design)

        assert not second_audit_entered.wait(timeout=0.25)
        release_first.set()
        assert first.result(timeout=2).mesh_hash == "test-hash"
        assert second.result(timeout=2).mesh_hash == "test-hash"

    assert audit_calls == 2


def test_same_design_builds_serialize_across_linux_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("fork")
    entered = context.Queue()
    completed = context.Queue()
    release = context.Event()
    design_id = "c" * 32
    first = context.Process(
        target=_process_build_worker,
        args=(str(tmp_path), design_id, entered, release, completed),
    )
    second = context.Process(
        target=_process_build_worker,
        args=(str(tmp_path), design_id, entered, release, completed),
    )

    first.start()
    try:
        entered.get(timeout=3)
        second.start()
        with pytest.raises(queue.Empty):
            entered.get(timeout=0.35)

        release.set()
        entered.get(timeout=3)
        results = [completed.get(timeout=3), completed.get(timeout=3)]
        assert all(status == "ok" for _, status, _ in results), results
    finally:
        release.set()
        for process in (first, second):
            if process.pid is not None:
                process.join(timeout=3)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=3)

    assert first.exitcode == 0
    assert second.exitcode == 0


def test_different_designs_do_not_share_a_global_build_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    object.__setattr__(config.settings, "output_dir", tmp_path)
    both_in_audit = threading.Barrier(2)

    def fake_audit_then_run(**_kwargs) -> SandboxResult:
        both_in_audit.wait(timeout=2)
        return _sandbox_result()

    def fake_build_from_sandbox_result(design: Design, *_args, **_kwargs) -> Build:
        return _build_result(design)

    monkeypatch.setattr(engine, "audit_then_run", fake_audit_then_run)
    monkeypatch.setattr(engine, "build_from_sandbox_result", fake_build_from_sandbox_result)

    with ThreadPoolExecutor(max_workers=2) as pool:
        builds = [
            pool.submit(engine.build_design, _design("d" * 32)),
            pool.submit(engine.build_design, _design("e" * 32)),
        ]
        assert [future.result(timeout=3).mesh_hash for future in builds] == [
            "test-hash",
            "test-hash",
        ]


def test_failed_build_releases_same_design_lock(tmp_path: Path, monkeypatch) -> None:
    object.__setattr__(config.settings, "output_dir", tmp_path)
    audit_calls = 0

    def fake_audit_then_run(**_kwargs) -> SandboxResult:
        nonlocal audit_calls
        audit_calls += 1
        if audit_calls == 1:
            raise engine.DesignBuildError("expected test failure")
        return _sandbox_result()

    def fake_build_from_sandbox_result(design: Design, *_args, **_kwargs) -> Build:
        return _build_result(design)

    monkeypatch.setattr(engine, "audit_then_run", fake_audit_then_run)
    monkeypatch.setattr(engine, "build_from_sandbox_result", fake_build_from_sandbox_result)
    design = _design("f" * 32)

    with pytest.raises(engine.DesignBuildError, match="expected test failure"):
        engine.build_design(design)

    assert engine.build_design(design).mesh_hash == "test-hash"
