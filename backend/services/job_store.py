from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import firestore as admin_firestore
from firebase_admin import storage as admin_storage

from config import settings

logger = logging.getLogger("job_store")

JOBS_COLLECTION = "three_d_jobs"


def _firebase_enabled() -> bool:
    return bool(settings.firebase_project_id or settings.firebase_storage_bucket)


def _init_firebase() -> None:
    if firebase_admin._apps:
        return
    options: Dict[str, str] = {}
    if settings.firebase_project_id:
        options["projectId"] = settings.firebase_project_id
    if settings.firebase_storage_bucket:
        options["storageBucket"] = settings.firebase_storage_bucket
    firebase_admin.initialize_app(options=options or None)


def _get_firestore() -> Optional[admin_firestore.Client]:
    if not _firebase_enabled():
        return None
    _init_firebase()
    return admin_firestore.client()


def _get_bucket() -> Optional[admin_storage.bucket.Bucket]:
    if not settings.firebase_storage_bucket:
        return None
    _init_firebase()
    return admin_storage.bucket(settings.firebase_storage_bucket)


def _build_storage_url(bucket_name: str, object_path: str) -> str:
    if settings.storage_public_base_url:
        return f"{settings.storage_public_base_url.rstrip('/')}/{object_path}"
    return f"https://storage.googleapis.com/{bucket_name}/{object_path}"


def _expand_dotted(payload: Dict[str, Any]) -> Dict[str, Any]:
    expanded: Dict[str, Any] = {}
    for key, value in payload.items():
        if "." not in key:
            expanded[key] = value
            continue
        parts = key.split(".")
        cursor = expanded
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return expanded


def ensure_job(job_id: str, data: Dict[str, Any]) -> None:
    client = _get_firestore()
    if client is None:
        return
    doc = client.collection(JOBS_COLLECTION).document(job_id)
    try:
        snapshot = doc.get()
    except Exception as exc:
        logger.warning("Firestore read failed: %s", exc)
        return

    payload = dict(data)
    payload["job_id"] = job_id
    payload["public"] = True
    payload["owner_id"] = "anon"
    payload["updated_at"] = admin_firestore.SERVER_TIMESTAMP
    if not snapshot.exists:
        payload["created_at"] = admin_firestore.SERVER_TIMESTAMP
        payload = _expand_dotted(payload)
        try:
            doc.set(payload, merge=True)
        except Exception as exc:
            logger.warning("Firestore create failed: %s", exc)
        return
    update_job(job_id, payload)


def update_job(job_id: str, data: Dict[str, Any]) -> None:
    client = _get_firestore()
    if client is None:
        return
    doc = client.collection(JOBS_COLLECTION).document(job_id)
    payload = dict(data)
    payload["updated_at"] = admin_firestore.SERVER_TIMESTAMP
    try:
        doc.update(payload)
    except Exception:
        try:
            doc.set(_expand_dotted(payload), merge=True)
        except Exception as exc:
            logger.warning("Firestore update failed: %s", exc)


def record_error(job_id: str, stage: str, message: str) -> None:
    update_job(
        job_id,
        {
            "status": "error",
            "error.stage": stage,
            "error.message": message,
        },
    )


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".glb":
        return "model/gltf-binary"
    if suffix == ".stl":
        return "model/stl"
    if suffix in {".gcode", ".gco"}:
        return "text/x.gcode"
    return "application/octet-stream"


def upload_artifact(job_id: str, path: Path) -> Optional[Dict[str, Any]]:
    bucket = _get_bucket()
    if bucket is None:
        return None
    object_path = f"three-d/jobs/{job_id}/{path.name}"
    blob = bucket.blob(object_path)
    blob.cache_control = "public, max-age=31536000"
    try:
        blob.upload_from_filename(str(path), content_type=_content_type_for_path(path))
        try:
            blob.make_public()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Storage upload failed: %s", exc)
        return None
    return {
        "object_path": object_path,
        "url": _build_storage_url(bucket.name, object_path),
        "size": path.stat().st_size,
        "content_type": _content_type_for_path(path),
    }
