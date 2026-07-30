"""Durable Firestore + Cloud Storage persistence for conversational designs.

The local filesystem remains a hot cache for CAD subprocesses. Firestore is
the source of truth for JSON state; Cloud Storage holds immutable artifacts.
All helpers are best-effort locally and active automatically on Cloud Run.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from firebase_admin import firestore as admin_firestore

from services import job_store


logger = logging.getLogger(__name__)
DESIGNS_COLLECTION = "three_d_designs"


def _client():
    return job_store._get_firestore()  # Reuse the app's single Admin SDK instance.


def _bucket():
    if os.getenv("PULSAI_DURABLE_ARTIFACTS", "").lower() not in {"1", "true", "yes"}:
        return None
    return job_store._get_bucket()


def save_design_payload(design_id: str, payload: dict[str, Any]) -> None:
    client = _client()
    if client is None:
        return
    try:
        client.collection(DESIGNS_COLLECTION).document(design_id).set(
            {
                "design_id": design_id,
                "design": payload,
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    except Exception as exc:
        logger.warning("Firestore design save failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable design save failed.") from exc


def load_design_payload(design_id: str) -> dict[str, Any] | None:
    client = _client()
    if client is None:
        return None
    try:
        snapshot = client.collection(DESIGNS_COLLECTION).document(design_id).get()
        if not snapshot.exists:
            return None
        payload = snapshot.to_dict() or {}
        design = payload.get("design")
        return design if isinstance(design, dict) else None
    except Exception as exc:
        logger.warning("Firestore design load failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable design load failed.") from exc


def list_design_payloads(limit: int = 100) -> list[dict[str, Any]]:
    client = _client()
    if client is None:
        return []
    try:
        query = (
            client.collection(DESIGNS_COLLECTION)
            .order_by("updated_at", direction=admin_firestore.Query.DESCENDING)
            .limit(limit)
        )
        out: list[dict[str, Any]] = []
        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            design = payload.get("design")
            if isinstance(design, dict):
                out.append(design)
        return out
    except Exception as exc:
        logger.warning("Firestore design list failed: %s", exc)
        raise RuntimeError("Durable design list failed.") from exc


def upload_build_artifacts(design_id: str, build: Any) -> None:
    bucket = _bucket()
    if bucket is None:
        return
    for kind, artifact in build.artifacts.items():
        path = Path(artifact.path)
        if not path.is_file():
            continue
        object_path = (
            f"three-d/designs/{design_id}/revisions/{build.revision_id}/"
            f"{kind}/{path.name}"
        )
        blob = bucket.blob(object_path)
        blob.cache_control = "public, max-age=31536000, immutable"
        content_type = mimetypes.guess_type(path.name)[0] or job_store._content_type_for_path(path)
        try:
            blob.upload_from_filename(str(path), content_type=content_type)
            artifact.url = job_store._build_storage_url(bucket.name, object_path)
            artifact.bytes = path.stat().st_size
        except Exception as exc:
            logger.warning("Storage artifact upload failed for %s: %s", object_path, exc)
            # Firestore still preserves the parametric source of truth. When
            # Storage is unavailable (for example, billing is not enabled),
            # the artifact is regenerated from that source after a cold start.
            continue


def save_build_payload(
    design_id: str,
    build_payload: dict[str, Any],
    *,
    design_payload: dict[str, Any] | None,
    feature_graph: dict[str, Any] | None,
) -> None:
    client = _client()
    if client is None:
        return
    doc = client.collection(DESIGNS_COLLECTION).document(design_id)
    try:
        doc.set(
            {
                "design_id": design_id,
                "latest_build": build_payload,
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        revision_id = str(build_payload.get("revision_id") or "")
        if revision_id:
            doc.collection("revisions").document(revision_id).set(
                {
                    "revision_id": revision_id,
                    "build": build_payload,
                    "design": design_payload,
                    "feature_graph": feature_graph,
                    "updated_at": admin_firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
    except Exception as exc:
        logger.warning("Firestore build save failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable build save failed.") from exc


def load_build_payload(design_id: str) -> dict[str, Any] | None:
    client = _client()
    if client is None:
        return None
    try:
        snapshot = client.collection(DESIGNS_COLLECTION).document(design_id).get()
        if not snapshot.exists:
            return None
        build = (snapshot.to_dict() or {}).get("latest_build")
        return build if isinstance(build, dict) else None
    except Exception as exc:
        logger.warning("Firestore build load failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable build load failed.") from exc


def save_conversation_payload(design_id: str, messages: list[dict[str, Any]]) -> None:
    client = _client()
    if client is None:
        return
    try:
        (
            client.collection(DESIGNS_COLLECTION)
            .document(design_id)
            .collection("state")
            .document("conversation")
            .set({"messages": messages, "updated_at": admin_firestore.SERVER_TIMESTAMP})
        )
    except Exception as exc:
        logger.warning("Firestore conversation save failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable conversation save failed.") from exc


def load_conversation_payload(design_id: str) -> list[dict[str, Any]] | None:
    client = _client()
    if client is None:
        return None
    try:
        snapshot = (
            client.collection(DESIGNS_COLLECTION)
            .document(design_id)
            .collection("state")
            .document("conversation")
            .get()
        )
        if not snapshot.exists:
            return None
        messages = (snapshot.to_dict() or {}).get("messages")
        return messages if isinstance(messages, list) else None
    except Exception as exc:
        logger.warning("Firestore conversation load failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable conversation load failed.") from exc


def list_revision_payloads(design_id: str, limit: int = 50) -> list[dict[str, Any]]:
    client = _client()
    if client is None:
        return []
    try:
        query = (
            client.collection(DESIGNS_COLLECTION)
            .document(design_id)
            .collection("revisions")
            .order_by("updated_at", direction=admin_firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [snapshot.to_dict() or {} for snapshot in query.stream()]
    except Exception as exc:
        logger.warning("Firestore revision list failed for %s: %s", design_id, exc)
        raise RuntimeError("Durable revision list failed.") from exc


def load_revision_payload(design_id: str, revision_id: str) -> dict[str, Any] | None:
    client = _client()
    if client is None:
        return None
    try:
        snapshot = (
            client.collection(DESIGNS_COLLECTION)
            .document(design_id)
            .collection("revisions")
            .document(revision_id)
            .get()
        )
        return snapshot.to_dict() if snapshot.exists else None
    except Exception as exc:
        logger.warning("Firestore revision load failed for %s/%s: %s", design_id, revision_id, exc)
        raise RuntimeError("Durable revision load failed.") from exc


def delete_revision_payload(design_id: str, revision_id: str) -> None:
    client = _client()
    if client is not None:
        try:
            (
                client.collection(DESIGNS_COLLECTION)
                .document(design_id)
                .collection("revisions")
                .document(revision_id)
                .delete()
            )
        except Exception as exc:
            logger.warning("Firestore revision delete failed for %s/%s: %s", design_id, revision_id, exc)
            raise RuntimeError("Durable revision delete failed.") from exc
    _delete_storage_prefix(f"three-d/designs/{design_id}/revisions/{revision_id}/")


def delete_design_payload(design_id: str) -> None:
    client = _client()
    if client is not None:
        try:
            doc = client.collection(DESIGNS_COLLECTION).document(design_id)
            for collection_name in ("revisions", "state"):
                for child in doc.collection(collection_name).stream():
                    child.reference.delete()
            doc.delete()
        except Exception as exc:
            logger.warning("Firestore design delete failed for %s: %s", design_id, exc)
            raise RuntimeError("Durable design delete failed.") from exc
    _delete_storage_prefix(f"three-d/designs/{design_id}/")


def upload_export_file(design_id: str, preset: str, path: Path) -> str | None:
    bucket = _bucket()
    if bucket is None or not path.is_file():
        return None
    object_path = f"three-d/designs/{design_id}/exports/{preset}/{path.name}"
    blob = bucket.blob(object_path)
    blob.cache_control = "private, max-age=0"
    try:
        blob.upload_from_filename(
            str(path),
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        return job_store._build_storage_url(bucket.name, object_path)
    except Exception as exc:
        logger.warning("Storage export upload failed for %s: %s", object_path, exc)
        return None


def _delete_storage_prefix(prefix: str) -> None:
    bucket = _bucket()
    if bucket is None:
        return
    try:
        for blob in bucket.list_blobs(prefix=prefix):
            blob.delete()
    except Exception as exc:
        logger.warning("Storage prefix delete failed for %s: %s", prefix, exc)


__all__ = [
    "save_design_payload",
    "load_design_payload",
    "list_design_payloads",
    "upload_build_artifacts",
    "save_build_payload",
    "load_build_payload",
    "save_conversation_payload",
    "load_conversation_payload",
    "list_revision_payloads",
    "load_revision_payload",
    "delete_revision_payload",
    "delete_design_payload",
    "upload_export_file",
]
