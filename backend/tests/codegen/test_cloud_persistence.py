from __future__ import annotations

import shutil
from pathlib import Path

import config
from services.codegen import cloud_store, store
from services.codegen.models import Build, BuildArtifact


def test_design_and_conversation_reload_from_durable_store(tmp_path: Path, monkeypatch) -> None:
    object.__setattr__(config.settings, "output_dir", tmp_path)
    remote: dict[str, object] = {}

    monkeypatch.setattr(cloud_store, "save_design_payload", lambda design_id, payload: remote.update(design=payload))
    monkeypatch.setattr(cloud_store, "load_design_payload", lambda design_id: remote.get("design"))
    monkeypatch.setattr(cloud_store, "save_conversation_payload", lambda design_id, messages: remote.update(conversation=messages))
    monkeypatch.setattr(cloud_store, "load_conversation_payload", lambda design_id: remote.get("conversation"))

    design = store.create_design(name="Persistent box", script="result = Box(10, 10, 10)")
    messages = [{"role": "user", "content": "make it taller"}]
    store.save_conversation(design.id, messages)

    shutil.rmtree(tmp_path / "designs" / design.id)

    assert store.get_design(design.id).name == "Persistent box"
    assert store.load_conversation(design.id) == messages


def test_build_reload_and_remote_revision_without_local_files(tmp_path: Path, monkeypatch) -> None:
    object.__setattr__(config.settings, "output_dir", tmp_path)
    remote: dict[str, object] = {}

    monkeypatch.setattr(cloud_store, "save_design_payload", lambda *_: None)
    monkeypatch.setattr(cloud_store, "load_design_payload", lambda *_: None)
    monkeypatch.setattr(cloud_store, "upload_build_artifacts", lambda design_id, build: None)
    monkeypatch.setattr(
        cloud_store,
        "save_build_payload",
        lambda design_id, build_payload, **kwargs: remote.update(
            build=build_payload,
            revision={"build": build_payload, "design": kwargs.get("design_payload")},
        ),
    )
    monkeypatch.setattr(cloud_store, "load_build_payload", lambda design_id: remote.get("build"))
    monkeypatch.setattr(cloud_store, "list_revision_payloads", lambda design_id: [remote["revision"]])

    design = store.create_design(name="Persistent build", script="result = Box(10, 10, 10)")
    artifact_path = tmp_path / "model.stl"
    artifact_path.write_bytes(b"solid test\nendsolid test\n")
    build = Build(
        revision_id=design.revision_id,
        mesh_hash="abc123",
        artifacts={
            "stl": BuildArtifact(
                kind="stl",
                url="/artifacts/model.stl",
                path=str(artifact_path),
                bytes=artifact_path.stat().st_size,
            )
        },
    )
    store.save_build(design.id, build)
    shutil.rmtree(tmp_path / "designs" / design.id)

    assert store.get_build(design.id).mesh_hash == "abc123"
    revisions = store.list_revisions(design.id)
    assert revisions[0]["revision_id"] == design.revision_id
    assert revisions[0]["mesh_hash"] == "abc123"
