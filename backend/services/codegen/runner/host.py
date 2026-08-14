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

import errno
import hashlib
import json
import os
import resource
import signal
import sys
import time
import traceback
import re
from pathlib import Path
from types import ModuleType


CPU_SECONDS = 90
ADDRESS_SPACE_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB
DEFAULT_MAX_ARTIFACT_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ARTIFACT_TOTAL_BYTES = 128 * 1024 * 1024


class ArtifactSizeLimitError(RuntimeError):
    """A generated artifact exceeded its per-file or aggregate byte budget."""


def apply_rlimits(
    max_file_bytes: int = DEFAULT_MAX_ARTIFACT_FILE_BYTES,
) -> None:
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
    fsize_resource = getattr(resource, "RLIMIT_FSIZE", None)
    if fsize_resource is not None:
        # Permit one sentinel byte beyond the configured maximum. If an
        # exporter reaches it, the explicit validation below can distinguish
        # a truncated oversized artifact from a valid file exactly at the
        # configured limit.
        file_limit = max(1, int(max_file_bytes)) + 1
        try:
            # Turn the default SIGXFSZ termination into EFBIG so the exporter
            # can unwind and the runner can return a structured safe failure.
            if hasattr(signal, "SIGXFSZ"):
                signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
            resource.setrlimit(fsize_resource, (file_limit, file_limit))
        except (ValueError, OSError):
            # Some development platforms do not implement RLIMIT_FSIZE. The
            # explicit post-export checks below remain authoritative there.
            pass


def _validate_artifact_sizes(
    artifacts: dict[str, str],
    *,
    per_file_bytes: int,
    aggregate_bytes: int,
) -> int:
    """Validate generated files before any staged artifact is persisted."""
    total = 0
    for kind, path_str in artifacts.items():
        path = Path(path_str)
        size = path.stat().st_size
        if size > per_file_bytes:
            raise ArtifactSizeLimitError(
                f"Generated {kind.upper()} artifact is {size} bytes; "
                f"per-file limit is {per_file_bytes} bytes."
            )
        total += size
        if total > aggregate_bytes:
            raise ArtifactSizeLimitError(
                f"Generated artifacts total {total} bytes; "
                f"aggregate limit is {aggregate_bytes} bytes."
            )
    return total


def _cleanup_staged_artifacts(workdir: Path, stage_prefix: str) -> None:
    for path in workdir.glob(f"{stage_prefix}*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def _is_file_size_limit_failure(
    exc: BaseException,
    workdir: Path,
    stage_prefix: str,
    per_file_bytes: int,
) -> bool:
    if isinstance(exc, OSError) and exc.errno == errno.EFBIG:
        return True
    for path in workdir.glob(f"{stage_prefix}*"):
        try:
            if path.is_file() and path.stat().st_size > per_file_bytes:
                return True
        except OSError:
            continue
    return False


def _write_artifact_limit_failure(
    result_path: Path,
    *,
    error: str,
    per_file_bytes: int,
    aggregate_bytes: int,
    log_lines: list[str],
) -> None:
    result_path.write_text(
        json.dumps(
            {
                "ok": False,
                "code": "artifact_size_limit_exceeded",
                "error": error,
                "artifact_limits": {
                    "per_file_bytes": per_file_bytes,
                    "aggregate_bytes": aggregate_bytes,
                },
                "log": "\n".join(log_lines),
            }
        )
    )


def _persist_staged_artifacts(
    workdir: Path,
    artifacts: dict[str, str],
) -> dict[str, str]:
    persisted: dict[str, str] = {}
    for kind, staged_path_str in artifacts.items():
        staged_path = Path(staged_path_str)
        final_path = workdir / f"model.{kind}"
        staged_path.replace(final_path)
        persisted[kind] = str(final_path)
    return persisted


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


def _feature_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_") or "feature"


def _shape_from_value(value):
    candidate = getattr(value, "part", None) or getattr(value, "shape", None) or value
    return candidate if callable(getattr(candidate, "faces", None)) else None


def _same_face(left, right) -> bool:
    try:
        return bool(left.wrapped.IsSame(right.wrapped))
    except Exception:
        return False


def _semantic_face_scene(result_obj, namespace: dict):
    """Create a selectable GLB scene and node→B-rep face contract.

    Triangle indexes change whenever tessellation changes.  Here every B-rep
    face becomes its own named GLB node; the API exposes a semantic reference
    based on surface class/orientation/order and, where possible, the smallest
    named source shape that owns that face.
    """
    shape = _shape_from_value(result_obj)
    if shape is None:
        return None, {}
    faces = list(shape.faces())
    if not faces or len(faces) > 800:
        return None, {}

    import numpy as np
    import trimesh

    candidate_shapes: list[tuple[str, object, list]] = []
    for name, value in namespace.items():
        if name.startswith("_") or name in {"result"}:
            continue
        candidate = _shape_from_value(value)
        if candidate is None:
            continue
        try:
            candidate_faces = list(candidate.faces())
        except Exception:
            continue
        if candidate_faces and len(candidate_faces) <= 800:
            candidate_shapes.append((name, candidate, candidate_faces))
    candidate_shapes.sort(key=lambda item: len(item[2]))

    labelled_children: list[tuple[str, list]] = []
    for child in list(getattr(result_obj, "children", []) or []):
        label = str(getattr(child, "label", "") or "").strip()
        child_shape = _shape_from_value(child)
        if not label or child_shape is None:
            continue
        try:
            labelled_children.append((label, list(child_shape.faces())))
        except Exception:
            continue

    classified: list[tuple[tuple, object, str, str | None, str | None]] = []
    for face in faces:
        try:
            center = face.center()
            normal = face.normal_at()
            surface = str(face.geom_type).split(".")[-1].lower()
            normal_values = (float(normal.X), float(normal.Y), float(normal.Z))
            dominant_index = max(range(3), key=lambda index: abs(normal_values[index]))
            dominant = "xyz"[dominant_index] + ("p" if normal_values[dominant_index] >= 0 else "n")
            sort_key = (
                surface,
                dominant,
                round(float(center.X), 6),
                round(float(center.Y), 6),
                round(float(center.Z), 6),
                round(float(face.area), 6),
            )
        except Exception:
            continue
        owner_name = None
        for candidate_name, _, candidate_faces in candidate_shapes:
            if any(_same_face(face, candidate_face) for candidate_face in candidate_faces):
                owner_name = candidate_name
                break
        assembly_label = None
        for label, child_faces in labelled_children:
            if any(_same_face(face, child_face) for child_face in child_faces):
                assembly_label = label
                break
        classified.append((sort_key, face, surface, owner_name, assembly_label))

    # A selectable semantic scene may replace the complete STL-derived
    # fallback only when every source face is represented. A complete preview
    # is more important than face selection for a model with one bad face.
    if len(classified) != len(faces):
        return None, {}

    classified.sort(key=lambda item: item[0])
    scene = trimesh.Scene()
    for label, _ in labelled_children:
        scene.graph.update(frame_to=label, frame_from=scene.graph.base_frame)
    selection_map: dict[str, dict] = {}
    counters: dict[tuple[str, str], int] = {}
    rotation = trimesh.transformations.rotation_matrix(-0.5 * 3.141592653589793, [1.0, 0.0, 0.0])
    for sort_key, face, surface, owner_name, assembly_label in classified:
        dominant = sort_key[1]
        counter_key = (surface, dominant)
        ordinal = counters.get(counter_key, 0)
        counters[counter_key] = ordinal + 1
        try:
            vertices, triangles = face.tessellate(0.05, 0.08)
            vertex_array = np.asarray([(v.X, v.Y, v.Z) for v in vertices], dtype=float)
            triangle_array = np.asarray(triangles, dtype=int)
            if not len(vertex_array) or not len(triangle_array):
                return None, {}
            mesh = trimesh.Trimesh(vertices=vertex_array, faces=triangle_array, process=False)
            mesh.apply_transform(rotation)
        except Exception:
            return None, {}
        feature_id = _feature_id(owner_name) if owner_name else None
        topology_ref = f"brep:face:{surface}:{dominant}:{ordinal}"
        node_name = f"p3d_face_{len(selection_map):04d}"
        scene.add_geometry(
            mesh,
            node_name=node_name,
            geom_name=node_name,
            **({"parent_node_name": assembly_label} if assembly_label else {}),
        )
        selection_map[node_name] = {
            "topology_ref": topology_ref,
            "feature_id": feature_id,
            "feature_name": owner_name,
            "surface_type": surface,
            "confidence": "feature_face" if feature_id else "face",
        }
    return (scene if selection_map else None), selection_map


def main() -> int:
    requested_file_limit = DEFAULT_MAX_ARTIFACT_FILE_BYTES
    if len(sys.argv) >= 3:
        try:
            requested_file_limit = max(1, int(sys.argv[2]))
        except (TypeError, ValueError):
            pass
    apply_rlimits(max_file_bytes=requested_file_limit)
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
    artifact_limits = job.get("artifact_limits", {}) or {}
    per_file_limit = max(
        1,
        int(artifact_limits.get("per_file_bytes", requested_file_limit)),
    )
    aggregate_limit = max(
        1,
        int(
            artifact_limits.get(
                "aggregate_bytes", DEFAULT_MAX_ARTIFACT_TOTAL_BYTES
            )
        ),
    )

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
    stage_prefix = f".artifact-{os.getpid()}-"

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
            stl_path = workdir / f"{stage_prefix}model.stl"
            step_path = workdir / f"{stage_prefix}model.step"

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
                    # Keep curved CAD features visually trustworthy in the viewer.
                    # 0.5 rad produced visibly faceted cups/holes; ~5 degrees is
                    # still lightweight while making cylinders read as round.
                    export_stl(result_obj, str(stl_path), tolerance=0.05, angular_tolerance=0.08)
                    artifacts["stl"] = str(stl_path)
                if "step" in targets:
                    try:
                        export_step(result_obj, str(step_path))
                        artifacts["step"] = str(step_path)
                    except Exception as exc:
                        if _is_file_size_limit_failure(
                            exc,
                            workdir,
                            stage_prefix,
                            per_file_limit,
                        ):
                            raise ArtifactSizeLimitError(
                                "Generated STEP artifact exceeded the per-file "
                                f"limit of {per_file_limit} bytes."
                            ) from exc
                        log_lines.append(f"step export skipped: {exc}")

            if "stl" in artifacts:
                import trimesh

                mesh = trimesh.load_mesh(stl_path, force="mesh")
                if not isinstance(mesh, trimesh.Trimesh):
                    mesh = trimesh.util.concatenate(tuple(mesh.dump()))
                # OCCT can emit isolated zero-area triangles where tangent
                # solids meet. They do not represent CAD geometry but make an
                # otherwise closed print fail the watertight gate. Remove only
                # degenerate faces, then persist the cleaned derived STL.
                valid_faces = mesh.nondegenerate_faces()
                if len(valid_faces) == len(mesh.faces) and not bool(valid_faces.all()):
                    mesh.update_faces(valid_faces)
                    mesh.remove_unreferenced_vertices()
                    mesh.export(stl_path)
                bbox_vec = mesh.bounding_box.extents
                bbox = (float(bbox_vec[0]), float(bbox_vec[1]), float(bbox_vec[2]))
                if "glb" in targets:
                    glb_path = workdir / f"{stage_prefix}model.glb"
                    # CAD scripts and STEP/STL use Z-up, while glTF viewers use
                    # Y-up.  Export a rotated copy so an upright part does not
                    # appear lying on its back in the browser.
                    glb_mesh = mesh.copy()
                    glb_mesh.apply_transform(
                        trimesh.transformations.rotation_matrix(
                            -0.5 * 3.141592653589793,
                            [1.0, 0.0, 0.0],
                        )
                    )
                    # Preserve a small, labelled top-level assembly when the
                    # CAD result provides one. A flattened STL is correct for
                    # printing, but it makes interactive motion impossible:
                    # the viewer cannot rotate the wheel without also rotating
                    # its stand. Labelled GLB nodes keep those parts separate.
                    glb_scene, selection_map = _semantic_face_scene(result_obj, namespace)
                    top_children = list(getattr(result_obj, "children", []) or [])
                    if glb_scene is None and type(result_obj).__name__ == "Compound" and 1 < len(top_children) <= 16:
                        candidate_scene = trimesh.Scene()
                        exported_parts = 0
                        used_labels = set()
                        for child_index, child in enumerate(top_children):
                            label = str(getattr(child, "label", "") or "").strip()
                            if not label or label in used_labels:
                                continue
                            used_labels.add(label)
                            part_path = workdir / f"{stage_prefix}glb-part-{child_index}.stl"
                            try:
                                export_stl(
                                    child,
                                    str(part_path),
                                    tolerance=0.05,
                                    angular_tolerance=0.08,
                                )
                                part_mesh = trimesh.load_mesh(part_path, force="mesh")
                                if not isinstance(part_mesh, trimesh.Trimesh):
                                    part_mesh = trimesh.util.concatenate(tuple(part_mesh.dump()))
                                part_mesh.apply_transform(
                                    trimesh.transformations.rotation_matrix(
                                        -0.5 * 3.141592653589793,
                                        [1.0, 0.0, 0.0],
                                    )
                                )
                                center = part_mesh.bounding_box.centroid
                                part_mesh.apply_translation(-center)
                                node_transform = trimesh.transformations.translation_matrix(center)
                                candidate_scene.add_geometry(
                                    part_mesh,
                                    node_name=label,
                                    geom_name=label,
                                    transform=node_transform,
                                )
                                exported_parts += 1
                            except Exception as exc:
                                if _is_file_size_limit_failure(
                                    exc,
                                    workdir,
                                    stage_prefix,
                                    per_file_limit,
                                ):
                                    raise ArtifactSizeLimitError(
                                        "Generated intermediate GLB artifact exceeded "
                                        f"the per-file limit of {per_file_limit} bytes."
                                    ) from exc
                                raise
                            finally:
                                part_path.unlink(missing_ok=True)
                        if exported_parts == len(top_children):
                            glb_scene = candidate_scene
                    (glb_scene if glb_scene is not None else trimesh.Scene(glb_mesh)).export(glb_path)
                    artifacts["glb"] = str(glb_path)
        except ArtifactSizeLimitError as exc:
            _cleanup_staged_artifacts(workdir, stage_prefix)
            _write_artifact_limit_failure(
                result_path,
                error=str(exc),
                per_file_bytes=per_file_limit,
                aggregate_bytes=aggregate_limit,
                log_lines=log_lines,
            )
            return 1
        except Exception as exc:
            limit_failure = _is_file_size_limit_failure(
                exc,
                workdir,
                stage_prefix,
                per_file_limit,
            )
            _cleanup_staged_artifacts(workdir, stage_prefix)
            if limit_failure:
                _write_artifact_limit_failure(
                    result_path,
                    error=(
                        "Generated 3D artifact exceeded the per-file "
                        f"limit of {per_file_limit} bytes."
                    ),
                    per_file_bytes=per_file_limit,
                    aggregate_bytes=aggregate_limit,
                    log_lines=log_lines,
                )
                return 1
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

            dxf_path = workdir / f"{stage_prefix}model.dxf"
            export_dxf(result_obj, str(dxf_path))
            artifacts["dxf"] = str(dxf_path)
        except Exception as exc:
            limit_failure = _is_file_size_limit_failure(
                exc,
                workdir,
                stage_prefix,
                per_file_limit,
            )
            if limit_failure:
                _cleanup_staged_artifacts(workdir, stage_prefix)
                _write_artifact_limit_failure(
                    result_path,
                    error=(
                        "Generated DXF artifact exceeded the per-file "
                        f"limit of {per_file_limit} bytes."
                    ),
                    per_file_bytes=per_file_limit,
                    aggregate_bytes=aggregate_limit,
                    log_lines=log_lines,
                )
                return 1
            log_lines.append(f"dxf export skipped: {exc}")

    try:
        _validate_artifact_sizes(
            artifacts,
            per_file_bytes=per_file_limit,
            aggregate_bytes=aggregate_limit,
        )
        artifacts = _persist_staged_artifacts(workdir, artifacts)
        _cleanup_staged_artifacts(workdir, stage_prefix)
    except ArtifactSizeLimitError as exc:
        _cleanup_staged_artifacts(workdir, stage_prefix)
        _write_artifact_limit_failure(
            result_path,
            error=str(exc),
            per_file_bytes=per_file_limit,
            aggregate_bytes=aggregate_limit,
            log_lines=log_lines,
        )
        return 1
    except Exception as exc:
        _cleanup_staged_artifacts(workdir, stage_prefix)
        result_path.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": f"artifact persistence failed: {type(exc).__name__}: {exc}",
                    "log": "\n".join(log_lines),
                }
            )
        )
        return 1

    mesh_hash = ""
    if "stl" in artifacts:
        mesh_hash = _hash_mesh_file(Path(artifacts["stl"]))

    declared = list(getattr(pulsai_mod, "__declared__", []))

    selection_map = locals().get("selection_map", {})
    result_path.write_text(
        json.dumps(
            {
                "ok": True,
                "artifacts": artifacts,
                "mesh_hash": mesh_hash,
                "bbox_mm": bbox,
                "named_features": _classify_named_features(namespace),
                "selection_map": selection_map,
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
