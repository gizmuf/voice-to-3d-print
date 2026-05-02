"""Sandbox subprocess entrypoint.

Runs *inside* the spawned subprocess (never imported by the FastAPI app).
Reads {workdir}/job.json with the script + parameter overrides, executes the
script with build123d in scope, exports STL/STEP/DXF/GLB, and writes
{workdir}/result.json with paths and metadata.

The runner provides a ``pulsai`` shim module so user scripts can declare
parameters in a uniform way::

    from pulsai import param

    outer_diameter = param("outer_diameter", 340.0, type="length_mm",
                            min=50, max=600, doc="Outer diameter")

When the orchestrator calls ``update_parameter``, the override is applied
before the script runs — ``param()`` returns the override instead of the
default.

Resource limits (POSIX) are applied by ``apply_rlimits()`` before importing
build123d so the heavy import counts against the memory budget. They are
intentionally generous enough for real CAD work.
"""

from __future__ import annotations

import hashlib
import json
import resource
import sys
import time
import traceback
from pathlib import Path
from types import ModuleType


CPU_SECONDS = 90
ADDRESS_SPACE_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB


def apply_rlimits() -> None:
    """Apply POSIX resource limits inside the subprocess.

    Called as the first thing in main(); we keep it small and fast so a script
    cannot stall before its CPU budget engages.
    """
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    except (ValueError, OSError):
        pass
    try:
        resource.setrlimit(
            resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES)
        )
    except (ValueError, OSError):
        # macOS rejects RLIMIT_AS for some processes; fall through silently —
        # the wall-clock subprocess timeout still bounds runaway scripts.
        pass


def _make_pulsai_module(overrides: dict[str, object]) -> ModuleType:
    """Create the in-process ``pulsai`` helper available to the user script."""
    pulsai = ModuleType("pulsai")
    declared: list[dict[str, object]] = []

    def param(
        name: str,
        default,
        *,
        type: str = "length_mm",
        min=None,
        max=None,
        step=None,
        choices=None,
        doc: str | None = None,
        locked: bool = False,
    ):
        value = overrides.get(name, default)
        declared.append(
            {
                "name": name,
                "value": value,
                "default": default,
                "type": type,
                "min": min,
                "max": max,
                "step": step,
                "choices": choices,
                "doc": doc,
                "locked": bool(locked),
            }
        )
        return value

    def expose(name: str, value):
        """Mark a value as a 'visible output' for the inspector."""
        declared.append(
            {
                "name": name,
                "value": value,
                "type": "output",
            }
        )
        return value

    pulsai.param = param  # type: ignore[attr-defined]
    pulsai.expose = expose  # type: ignore[attr-defined]
    pulsai.__declared__ = declared  # type: ignore[attr-defined]
    return pulsai


def _hash_mesh_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def _classify_named_features(namespace: dict) -> list[dict]:
    """Pull out top-level variables that look like CAD objects."""
    interesting_classes = (
        "Part",
        "Sketch",
        "Compound",
        "Solid",
        "Shell",
        "Face",
        "Wire",
        "Edge",
    )
    out: list[dict] = []
    for key, value in namespace.items():
        if key.startswith("_") or key in {"param", "expose", "result"}:
            continue
        cls = type(value).__name__
        if cls in interesting_classes:
            entry = {"name": key, "kind": cls}
            try:
                bbox = value.bounding_box()  # build123d API
                entry["bbox_min"] = [bbox.min.X, bbox.min.Y, bbox.min.Z]
                entry["bbox_max"] = [bbox.max.X, bbox.max.Y, bbox.max.Z]
            except Exception:
                pass
            out.append(entry)
    return out


def main() -> int:
    apply_rlimits()
    started = time.perf_counter()

    if len(sys.argv) < 2:
        sys.stderr.write("usage: host.py <workdir>\n")
        return 2
    workdir = Path(sys.argv[1])
    job_path = workdir / "job.json"
    result_path = workdir / "result.json"

    try:
        job = json.loads(job_path.read_text())
    except Exception as exc:
        result_path.write_text(
            json.dumps({"ok": False, "error": f"cannot read job.json: {exc}"})
        )
        return 1

    script: str = job["script"]
    overrides: dict[str, object] = job.get("parameter_overrides", {}) or {}
    targets: list[str] = job.get("targets", ["stl", "step", "glb"])
    imported_files: dict[str, str] = job.get("imported_files", {}) or {}

    # Pre-import build123d so the import time hits the rlimit budget early
    # and the user script gets a fast first call.
    try:
        import build123d as _b3d
    except Exception as exc:  # pragma: no cover
        result_path.write_text(
            json.dumps({"ok": False, "error": f"build123d import failed: {exc}"})
        )
        return 1

    # Build the namespace the user script runs in.
    pulsai_mod = _make_pulsai_module(overrides)
    sys.modules["pulsai"] = pulsai_mod
    namespace: dict = {
        "__name__": "__pulsai_design__",
        "__doc__": None,
        # `from build123d import *` is the convention; we also expose it directly
        # so scripts can omit the wildcard import.
        **{k: getattr(_b3d, k) for k in dir(_b3d) if not k.startswith("_")},
    }

    # Pre-load any imported file into the namespace. STL uploads become
    # `imported_mesh` (trimesh.Trimesh); STEP uploads become `imported_part`
    # (build123d Compound). The script never sees file IO directly.
    if imported_files:
        for var_name, file_path in imported_files.items():
            try:
                ext = Path(file_path).suffix.lower()
                if ext in {".step", ".stp"} or var_name == "imported_part":
                    from build123d import import_step  # type: ignore

                    namespace[var_name] = import_step(file_path)
                else:
                    import trimesh

                    mesh = trimesh.load_mesh(file_path, force="mesh")
                    if not isinstance(mesh, trimesh.Trimesh):
                        mesh = trimesh.util.concatenate(tuple(mesh.dump()))
                    namespace[var_name] = mesh
            except Exception as exc:
                result_path.write_text(
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                f"Could not load imported file '{var_name}' "
                                f"from {file_path}: {exc}"
                            ),
                        }
                    )
                )
                return 1

    log_lines: list[str] = []

    def _log(msg: str) -> None:
        log_lines.append(msg)

    namespace["log"] = _log

    try:
        compiled = compile(script, "<design>", "exec")
        exec(compiled, namespace)
    except SystemExit as exc:
        result_path.write_text(
            json.dumps(
                {"ok": False, "error": f"script called sys.exit({exc.code!r})"}
            )
        )
        return 1
    except Exception as exc:
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(limit=10),
                    "log": "\n".join(log_lines),
                }
            )
        )
        return 1

    result_obj = namespace.get("result")
    if result_obj is None:
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "Script did not assign `result`. Set `result = <Part|Compound|Sketch>` "
                        "as the last expression so the engine can export it."
                    ),
                    "log": "\n".join(log_lines),
                }
            )
        )
        return 1

    artifacts: dict[str, str] = {}
    bbox: tuple[float, float, float] | None = None

    # Detect result type — trimesh meshes get a fast direct path; build123d
    # shapes go through OCCT exporters.
    result_is_mesh = False
    try:
        import trimesh as _tri

        if isinstance(result_obj, _tri.Trimesh):
            result_is_mesh = True
    except Exception:
        pass

    needs_3d = any(t in targets for t in ("stl", "step", "glb"))
    if needs_3d:
        try:
            stl_path = workdir / "model.stl"
            step_path = workdir / "model.step"

            if result_is_mesh:
                # Direct trimesh export — no OCCT round-trip. STEP is not
                # produced from a mesh result (B-rep doesn't fit; user can
                # convert if needed via a build123d wrapper).
                if "stl" in targets:
                    result_obj.export(stl_path)  # type: ignore[union-attr]
                    artifacts["stl"] = str(stl_path)
                if "step" in targets:
                    log_lines.append(
                        "step export skipped: result is a mesh; STEP requires a build123d Part/Compound."
                    )
            else:
                from build123d import export_stl, export_step

                if "stl" in targets:
                    export_stl(result_obj, str(stl_path), tolerance=0.05, angular_tolerance=0.5)
                    artifacts["stl"] = str(stl_path)
                if "step" in targets:
                    try:
                        export_step(result_obj, str(step_path))
                        artifacts["step"] = str(step_path)
                    except Exception as exc:
                        log_lines.append(f"step export skipped: {exc}")

            if "stl" in artifacts:
                import trimesh

                mesh = trimesh.load_mesh(stl_path, force="mesh")
                if not isinstance(mesh, trimesh.Trimesh):
                    mesh = trimesh.util.concatenate(tuple(mesh.dump()))
                bbox_vec = mesh.bounding_box.extents
                bbox = (float(bbox_vec[0]), float(bbox_vec[1]), float(bbox_vec[2]))
                if "glb" in targets:
                    glb_path = workdir / "model.glb"
                    trimesh.Scene(mesh).export(glb_path)
                    artifacts["glb"] = str(glb_path)
        except Exception as exc:
            result_path.write_text(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"export failed: {type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(limit=10),
                        "log": "\n".join(log_lines),
                    }
                )
            )
            return 1

    # 2D outline → DXF (best-effort; CAM handoff)
    if "dxf" in targets:
        try:
            from build123d import export_dxf

            dxf_path = workdir / "model.dxf"
            export_dxf(result_obj, str(dxf_path))
            artifacts["dxf"] = str(dxf_path)
        except Exception as exc:
            log_lines.append(f"dxf export skipped: {exc}")

    mesh_hash = ""
    if "stl" in artifacts:
        mesh_hash = _hash_mesh_file(Path(artifacts["stl"]))

    declared = list(getattr(pulsai_mod, "__declared__", []))

    result_path.write_text(
        json.dumps(
            {
                "ok": True,
                "artifacts": artifacts,
                "mesh_hash": mesh_hash,
                "bbox_mm": bbox,
                "named_features": _classify_named_features(namespace),
                "declared_parameters": declared,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "log": "\n".join(log_lines),
            },
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
