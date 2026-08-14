from __future__ import annotations

from pathlib import Path

import config
from services import job_store


class _FakeBlob:
    def __init__(self) -> None:
        self.cache_control = ""
        self.public_calls = 0
        self.uploads: list[tuple[str, str | None]] = []

    def upload_from_filename(self, path: str, content_type: str | None = None) -> None:
        self.uploads.append((path, content_type))

    def make_public(self) -> None:
        self.public_calls += 1


class _FakeBucket:
    name = "private-test-bucket"

    def __init__(self) -> None:
        self.created: dict[str, _FakeBlob] = {}

    def blob(self, object_path: str) -> _FakeBlob:
        blob = self.created.setdefault(object_path, _FakeBlob())
        return blob


def test_uploaded_artifact_stays_private_and_uses_backend_proxy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_public = config.settings.allow_public_artifacts
    bucket = _FakeBucket()
    artifact = tmp_path / "model.stl"
    artifact.write_text("solid test\nendsolid test\n")
    object.__setattr__(config.settings, "allow_public_artifacts", False)
    monkeypatch.setattr(job_store, "_get_bucket", lambda: bucket)
    try:
        result = job_store.upload_artifact("abc123", artifact)
    finally:
        object.__setattr__(config.settings, "allow_public_artifacts", original_public)

    assert result is not None
    assert result["url"] == "/cloud-artifacts/three-d/jobs/abc123/model.stl"
    blob = bucket.created["three-d/jobs/abc123/model.stl"]
    assert blob.public_calls == 0
    assert blob.cache_control == "private, max-age=0, no-store"
