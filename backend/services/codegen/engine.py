"""High-level orchestrator for code-driven CAD.

Public surface:

- ``audit_then_run(...)`` — single shot: AST audit → sandbox → return SandboxResult.
- ``build_design(design, ...)`` — produce a Build record (artifacts + manufacturability)
  for a Design. This is what the AI agent's ``run_build`` tool calls.
- ``execute_for_parameters(design, overrides, ...)`` — fast path used by ``update_parameter``.

Artifacts are written to ``settings.output_dir / "designs" / {design_id}``. The
URLs returned are local ``/artifacts/...`` paths; the FastAPI app mounts that
directory.
"""

from __future__ import annotations

import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Iterable

from config import settings
from services.codegen.ast_audit import audit_script
from services.codegen.models import (
    Build,
    BuildArtifact,
    Design,
    DesignParameter,
    ManufacturabilityIssue,
    ManufacturabilityReport,
    NamedFeature,
)
from services.codegen.sandbox import SandboxResult, run_design
from services.printer_profiles import PrinterProfile, get_profile


SUPPORTED_TARGETS: tuple[str, ...] = ("stl", "step", "dxf", "glb")


class DesignBuildError(RuntimeError):
    """Raised when a build cannot be produced (audit fail, sandbox fail, etc.)."""

    def __init__(self, message: str, *, audit_errors: list[str] | None = None, sandbox: SandboxResult | None = None) -> None:
        super().__init__(message)
        self.audit_errors = audit_errors or []
        self.sandbox = sandbox


def _design_workdir(design_id: str) -> Path:
    path = settings.output_dir / "designs" / design_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _artifact_url(design_id: str, file_name: str) -> str:
    return f"/artifacts/designs/{design_id}/{file_name}"


def _coerce_targets(requested: Iterable[str] | None) -> list[str]:
    if requested is None:
        return ["stl", "step", "glb"]
    out = [t for t in requested if t in SUPPORTED_TARGETS]
    if not out:
        out = ["stl", "step", "glb"]
    return out


def audit_then_run(
    *,
    script: str,
    parameter_overrides: dict | None = None,
    targets: Iterable[str] | None = None,
    workspace_dir: Path | None = None,
    imported_files: dict[str, str] | None = None,
) -> SandboxResult:
    """AST-audit a script and run it in the sandbox.

    Raises :class:`DesignBuildError` if the audit fails (the sandbox is never
    spawned). Sandbox failures are returned as ``ok=False`` SandboxResult,
    not raised — callers decide whether to retry, surface to the agent, or
    bubble up.
    """
    audit = audit_script(script)
    if not audit.ok:
        raise DesignBuildError(
            "Script failed AST audit; refusing to run.",
            audit_errors=audit.errors,
        )
    return run_design(
        script=script,
        parameter_overrides=parameter_overrides or {},
        targets=_coerce_targets(targets),
        workspace_dir=workspace_dir,
        imported_files=imported_files,
    )


def parameter_snapshot(design: Design, overrides: dict | None = None) -> dict:
    """The effective parameter dict (defaults overridden)."""
    snap = {p.name: p.value for p in design.parameters}
    if overrides:
        snap.update(overrides)
    return snap


def build_design(
    design: Design,
    *,
    targets: Iterable[str] | None = None,
    parameter_overrides: dict | None = None,
    printer_profile_id: str | None = None,
    process: str = "fdm",
) -> Build:
    """Run a design end-to-end and produce a Build record.

    Audit → sandbox → mesh load → manufacturability → Build.

    If ``parameter_overrides`` is None, the design's current ``parameters``
    list (which reflects user slider edits and prior agent mutations) is
    automatically used. Without this, every build silently reverts to the
    defaults baked into the script source — the slider edits would never
    actually reach the geometry pipeline.
    """
    started = time.perf_counter()
    workdir = _design_workdir(design.id)
    imported_files = design.metadata.get("imported_files") or None
    if parameter_overrides is None:
        parameter_overrides = {p.name: p.value for p in design.parameters}
    sandbox_result = audit_then_run(
        script=design.script,
        parameter_overrides=parameter_overrides,
        targets=targets,
        workspace_dir=workdir,
        imported_files=imported_files,
    )

    if not sandbox_result.ok:
        raise DesignBuildError(
            f"Sandbox build failed: {sandbox_result.payload.get('error')}",
            sandbox=sandbox_result,
        )

    return build_from_sandbox_result(
        design,
        sandbox_result,
        parameter_overrides=parameter_overrides,
        printer_profile_id=printer_profile_id,
        process=process,
        started=started,
    )


def build_from_sandbox_result(
    design: Design,
    sandbox_result,
    *,
    parameter_overrides: dict | None = None,
    printer_profile_id: str | None = None,
    process: str = "fdm",
    started: float | None = None,
) -> Build:
    """Synthesize a Build record from an existing SandboxResult.

    Used when the caller already ran the sandbox (e.g. /design/create needs
    derived parameters/features and a Build from the same payload, without
    paying twice).
    """
    started = started if started is not None else time.perf_counter()

    artifacts: dict[str, BuildArtifact] = {}
    for kind, path_str in (sandbox_result.payload.get("artifacts") or {}).items():
        path = Path(path_str)
        if not path.exists():
            continue
        artifacts[kind] = BuildArtifact(
            kind=kind,  # type: ignore[arg-type]
            url=_artifact_url(design.id, path.name),
            path=str(path),
            bytes=path.stat().st_size,
        )

    mesh_hash = sandbox_result.payload.get("mesh_hash") or ""
    bbox = sandbox_result.payload.get("bbox_mm")

    manufacturability_report: ManufacturabilityReport | None = None
    if "stl" in artifacts:
        manufacturability_report = run_manufacturability(
            stl_path=Path(artifacts["stl"].path),
            process=process,
            printer_profile_id=printer_profile_id,
        )

    return Build(
        revision_id=design.revision_id,
        mesh_hash=mesh_hash,
        bounding_box_mm=tuple(bbox) if bbox else None,
        artifacts=artifacts,
        manufacturability=manufacturability_report,
        parameter_snapshot=parameter_snapshot(design, parameter_overrides),
        duration_ms=int((time.perf_counter() - started) * 1000),
        log=sandbox_result.payload.get("log") or "",
    )


def derive_named_features(
    sandbox_payload: dict,
    script: str,
    *,
    previous_features: list[NamedFeature] | None = None,
    revision_id: str = "",
    created_by: str = "system",
    source_prompt: str | None = None,
) -> list[NamedFeature]:
    """Pull NamedFeature records from the runner's classification."""
    previous_by_name = {f.name: f for f in previous_features or []}
    out: list[NamedFeature] = []
    for entry in sandbox_payload.get("named_features") or []:
        name = entry.get("name", "")
        prev = previous_by_name.get(name)
        out.append(
            NamedFeature(
                id=prev.id if prev else "",
                name=name,
                kind=entry.get("kind", "block"),
                source="",
                parent_feature_ids=prev.parent_feature_ids if prev else [],
                created_by=prev.created_by if prev else created_by,  # type: ignore[arg-type]
                source_prompt=prev.source_prompt if prev else source_prompt,
                revision_id=prev.revision_id if prev else revision_id,
                user_words=prev.user_words if prev else [],
            )
        )
    # Also extract `# @feature: name` blocks from the script.
    out.extend(
        _extract_feature_blocks(
            script,
            previous_by_name=previous_by_name,
            revision_id=revision_id,
            created_by=created_by,
            source_prompt=source_prompt,
        )
    )
    return _dedupe_named_features(out)


def _dedupe_named_features(features: list[NamedFeature]) -> list[NamedFeature]:
    """Merge duplicate feature records while preferring script-block metadata."""
    merged: dict[tuple[str, str], NamedFeature] = {}
    order: list[tuple[str, str]] = []
    for feature in features:
        key = (feature.id, feature.kind)
        existing = merged.get(key)
        if existing is None:
            merged[key] = feature
            order.append(key)
            continue
        if feature.source and not existing.source:
            merged[key] = feature
        else:
            existing.source = existing.source or feature.source
            existing.parameters_used = sorted(
                set(existing.parameters_used) | set(feature.parameters_used)
            )
            existing.parent_feature_ids = sorted(
                set(existing.parent_feature_ids) | set(feature.parent_feature_ids)
            )
            existing.user_words = list(dict.fromkeys([*existing.user_words, *feature.user_words]))
    return [merged[key] for key in order]


def derive_parameters(sandbox_payload: dict) -> list[DesignParameter]:
    out: list[DesignParameter] = []
    for entry in sandbox_payload.get("declared_parameters") or []:
        if entry.get("type") == "output":
            continue
        out.append(
            DesignParameter(
                name=entry["name"],
                value=entry.get("value", entry.get("default")),
                type=entry.get("type") or "length_mm",
                min=entry.get("min"),
                max=entry.get("max"),
                step=entry.get("step"),
                choices=entry.get("choices"),
                doc=entry.get("doc"),
                locked=bool(entry.get("locked", False)),
            )
        )
    return out


def _feature_from_block(
    *,
    name: str,
    source: str,
    previous_by_name: dict[str, NamedFeature],
    revision_id: str,
    created_by: str,
    source_prompt: str | None,
) -> NamedFeature:
    prev = previous_by_name.get(name)
    return NamedFeature(
        id=prev.id if prev else "",
        name=name,
        kind="block",
        source=source,
        parameters_used=prev.parameters_used if prev else [],
        parent_feature_ids=prev.parent_feature_ids if prev else [],
        created_by=prev.created_by if prev else created_by,  # type: ignore[arg-type]
        source_prompt=prev.source_prompt if prev else source_prompt,
        revision_id=prev.revision_id if prev else revision_id,
        user_words=prev.user_words if prev else [],
    )


def _extract_feature_blocks(
    script: str,
    *,
    previous_by_name: dict[str, NamedFeature] | None = None,
    revision_id: str = "",
    created_by: str = "system",
    source_prompt: str | None = None,
) -> list[NamedFeature]:
    """Parse `# @feature: name ... # @end` blocks out of a script."""
    previous_by_name = previous_by_name or {}
    out: list[NamedFeature] = []
    lines = script.splitlines()
    current_name: str | None = None
    current_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# @feature:"):
            if current_name is not None:
                out.append(
                    _feature_from_block(
                        name=current_name,
                        source="\n".join(current_lines),
                        previous_by_name=previous_by_name,
                        revision_id=revision_id,
                        created_by=created_by,
                        source_prompt=source_prompt,
                    )
                )
            current_name = stripped[len("# @feature:") :].strip() or "unnamed"
            current_lines = []
        elif stripped == "# @end" and current_name is not None:
            out.append(
                _feature_from_block(
                    name=current_name,
                    source="\n".join(current_lines),
                    previous_by_name=previous_by_name,
                    revision_id=revision_id,
                    created_by=created_by,
                    source_prompt=source_prompt,
                )
            )
            current_name = None
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        out.append(
            _feature_from_block(
                name=current_name,
                source="\n".join(current_lines),
                previous_by_name=previous_by_name,
                revision_id=revision_id,
                created_by=created_by,
                source_prompt=source_prompt,
            )
        )
    return out


def run_manufacturability(
    *,
    stl_path: Path,
    process: str = "fdm",
    printer_profile_id: str | None = None,
) -> ManufacturabilityReport:
    """Process-aware manufacturability against the freshly built STL."""
    started = time.perf_counter()
    profile = get_profile(printer_profile_id)
    issues: list[ManufacturabilityIssue] = []

    import trimesh

    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]

    bbox = tuple(float(v) for v in mesh.bounding_box.extents)

    if not mesh.is_watertight:
        issues.append(
            ManufacturabilityIssue(
                severity="error",
                code="non_watertight",
                message="Mesh is not watertight — has holes or open edges.",
                process="any",
                suggestion="Repair via MeshLib or reconsider the boolean operations producing this shape.",
            )
        )
    if not mesh.is_winding_consistent:
        issues.append(
            ManufacturabilityIssue(
                severity="warn",
                code="winding_inconsistent",
                message="Face normals are inconsistent.",
                process="any",
            )
        )

    if process == "fdm":
        issues.extend(_fdm_checks(mesh, profile))
    elif process == "cnc":
        issues.extend(_cnc_checks(mesh, profile))

    bx, by, bz = profile.bed_size_mm
    if bbox[0] > bx or bbox[1] > by or bbox[2] > bz:
        issues.append(
            ManufacturabilityIssue(
                severity="error",
                code="exceeds_bed",
                message=(
                    f"Model {bbox[0]:.1f}×{bbox[1]:.1f}×{bbox[2]:.1f}mm exceeds the "
                    f"{profile.label} build volume ({bx}×{by}×{bz} mm)."
                ),
                process="any",
                suggestion="Scale the model down or pick a larger printer profile.",
            )
        )

    if any(i.severity == "error" for i in issues):
        status = "unprintable"
    elif any(i.severity == "warn" for i in issues):
        status = "warn"
    else:
        status = "safe"

    digest = hashlib.sha256()
    with stl_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    mesh_hash = digest.hexdigest()[:16]

    return ManufacturabilityReport(
        process=process,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        issues=issues,
        estimated_volume_mm3=float(abs(mesh.volume)) if mesh.is_volume else None,
        bounding_box_mm=bbox,
        mesh_hash=mesh_hash,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _fdm_checks(mesh, profile: PrinterProfile) -> list[ManufacturabilityIssue]:
    """Overhang + thin-wall heuristics for FDM 3D printing."""
    import math

    import numpy as np
    import trimesh

    issues: list[ManufacturabilityIssue] = []

    if len(mesh.faces) == 0:
        return issues

    cos_threshold = math.cos(math.radians(45))
    normals = mesh.face_normals
    down = -normals[:, 2]
    overhanging = down > cos_threshold
    if bool(np.any(overhanging)):
        overhang_area = float(mesh.area_faces[overhanging].sum())
        total_area = float(mesh.area_faces.sum()) or 1.0
        fraction = overhang_area / total_area
        if fraction >= 0.02:
            severity = "error" if fraction > 0.20 else "warn"
            centroid_idx = int(np.argmax(mesh.area_faces * overhanging))
            location = tuple(float(c) for c in mesh.triangles_center[centroid_idx])
            issues.append(
                ManufacturabilityIssue(
                    severity=severity,  # type: ignore[arg-type]
                    code="overhang_steep",
                    message=f"~{fraction*100:.0f}% of surface area overhangs at >45°.",
                    location=location,
                    process="fdm",
                    suggestion="Add support material, reorient on the build plate, or chamfer the overhang.",
                )
            )

    # Sampled inward ray-cast for min wall.
    if mesh.is_watertight:
        try:
            samples = 250
            threshold = max(profile.nozzle_mm * 2.0, 0.8)
            seed_digest = hashlib.sha256()
            seed_digest.update(np.ascontiguousarray(mesh.vertices).tobytes())
            seed_digest.update(np.ascontiguousarray(mesh.faces).tobytes())
            seed = int(seed_digest.hexdigest()[:8], 16)
            points, face_indices = trimesh.sample.sample_surface(
                mesh=mesh,
                count=samples,
                seed=seed,
            )
            if len(points):
                normals_sampled = mesh.face_normals[face_indices]
                epsilon = max(profile.nozzle_mm * 0.1, 0.01)
                origins = points - normals_sampled * epsilon
                directions = -normals_sampled
                locations, ray_index, _ = mesh.ray.intersects_location(
                    ray_origins=origins, ray_directions=directions, multiple_hits=False
                )
                if len(ray_index):
                    distances = np.linalg.norm(locations - origins[ray_index], axis=1)
                    thinnest = float(distances.min())
                    if thinnest < threshold:
                        severity = "error" if thinnest < profile.nozzle_mm * 1.5 else "warn"
                        worst = int(np.argmin(distances))
                        location = tuple(float(c) for c in points[ray_index[worst]])
                        issues.append(
                            ManufacturabilityIssue(
                                severity=severity,  # type: ignore[arg-type]
                                code="min_wall_thin",
                                message=(
                                    f"Wall thickness as low as {thinnest:.2f} mm "
                                    f"(threshold {threshold:.2f} mm)."
                                ),
                                location=location,
                                process="fdm",
                                suggestion="Thicken thin sections to at least 2× nozzle diameter.",
                            )
                        )
        except Exception:  # pragma: no cover — ray engine missing or mesh degenerate
            pass

    return issues


def _cnc_checks(mesh, profile: PrinterProfile) -> list[ManufacturabilityIssue]:
    """CNC-specific heuristics: undercuts, internal-corner radii, thin features.

    Phase 1 of the CNC path — heuristics, not full toolpath simulation. Good
    enough to flag designs that are obviously not millable.
    """
    import math

    import numpy as np

    issues: list[ManufacturabilityIssue] = []
    if len(mesh.faces) == 0:
        return issues

    # Undercut: any face with normal pointing downward (relative to default Z+
    # tool orientation) is unreachable from a 3-axis mill in the current setup.
    normals = mesh.face_normals
    underside = normals[:, 2] < -0.1  # face normal has a downward component
    if bool(np.any(underside)):
        undercut_area = float(mesh.area_faces[underside].sum())
        total_area = float(mesh.area_faces.sum()) or 1.0
        fraction = undercut_area / total_area
        if fraction >= 0.02:
            centroid_idx = int(np.argmax(mesh.area_faces * underside))
            location = tuple(float(c) for c in mesh.triangles_center[centroid_idx])
            severity = "error" if fraction > 0.20 else "warn"
            issues.append(
                ManufacturabilityIssue(
                    severity=severity,  # type: ignore[arg-type]
                    code="cnc_undercut",
                    message=(
                        f"~{fraction*100:.0f}% of surfaces face downward — unreachable "
                        "by a 3-axis mill from above. Flip, split, or mill from both sides."
                    ),
                    location=location,
                    process="cnc",
                    suggestion="Reorient stock, design as two halves, or use a 4/5-axis fixture.",
                )
            )

    # Steep internal walls without filleting suggest an EDM-style square corner.
    # Build123d / OCCT preserves edge curves; we approximate by looking at the
    # angle distribution between adjacent faces.
    try:
        face_adjacency_angles = mesh.face_adjacency_angles
        sharp = face_adjacency_angles > math.radians(85)
        if bool(np.any(sharp)) and float(np.mean(sharp)) > 0.10:
            issues.append(
                ManufacturabilityIssue(
                    severity="warn",
                    code="cnc_sharp_corner",
                    message=(
                        "Many sharp internal corners detected; CNC end mills cannot reach "
                        "true zero-radius corners. Add a fillet equal to or larger than "
                        "the smallest tool diameter you plan to use."
                    ),
                    process="cnc",
                    suggestion="Apply fillet of 2–4 mm to internal corners.",
                )
            )
    except Exception:
        pass

    return issues


__all__ = [
    "audit_then_run",
    "build_design",
    "derive_named_features",
    "derive_parameters",
    "run_manufacturability",
    "DesignBuildError",
    "parameter_snapshot",
]
