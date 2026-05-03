"""Revision pruning bounds disk usage without orphaning the head."""

import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def store_with_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import config
    # Settings is frozen; bypass for the test only.
    object.__setattr__(config.settings, "output_dir", tmp_path)
    from services.codegen import store as store_module

    from services.codegen.models import Build, Design

    design_id = "test-design"
    chain: list[str] = []
    parent: str | None = None
    for i in range(25):
        rev = f"rev-{i:02d}"
        chain.append(rev)
        design = Design(
            id=design_id,
            revision_id=rev,
            parent_revision_id=parent,
            name="t",
            script="",
        )
        store_module.save_design(design)
        # Touch the revision dir (save_build prunes, so we have to bypass it
        # for the seed and then call prune explicitly per-test).
        rev_dir = Path(tmp_path) / "designs" / design_id / "revisions" / rev
        rev_dir.mkdir(parents=True, exist_ok=True)
        build = Build(revision_id=rev, mesh_hash=f"hash-{i}", parameter_snapshot={})
        (rev_dir / "build.json").write_text(json.dumps(build.model_dump(mode="json")))
        (rev_dir / "design.json").write_text(json.dumps(design.model_dump(mode="json")))
        # Stagger mtimes so newer revisions have larger mtime.
        ts = 1_700_000_000 + i
        os.utime(rev_dir / "build.json", (ts, ts))
        parent = rev
    return store_module, design_id, chain


def test_prune_keeps_last_n_and_head_without_full_parent_chain(store_with_chain):
    store_module, design_id, chain = store_with_chain
    deleted = store_module.prune_revisions(design_id, keep_last=5)
    revisions_dir = Path(store_module._design_dir(design_id)) / "revisions"
    remaining = {p.name for p in revisions_dir.iterdir() if p.is_dir()}
    assert remaining == set(chain[-5:]), remaining
    assert deleted == 20


def test_prune_drops_unlinked_revisions(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    import config
    object.__setattr__(config.settings, "output_dir", tmp_path)
    from services.codegen import store as store_module
    from services.codegen.models import Build, Design

    design_id = "test-d2"
    head = Design(id=design_id, revision_id="head", name="t", script="")
    store_module.save_design(head)
    head_dir = Path(tmp_path) / "designs" / design_id / "revisions" / "head"
    head_dir.mkdir(parents=True, exist_ok=True)
    (head_dir / "build.json").write_text(json.dumps(Build(revision_id="head", mesh_hash="h").model_dump(mode="json")))
    (head_dir / "design.json").write_text(json.dumps(head.model_dump(mode="json")))
    os.utime(head_dir / "build.json", (1_700_000_100, 1_700_000_100))

    # Five orphan revisions with no parent linkage to head.
    for i in range(5):
        rev = f"orphan-{i}"
        rev_dir = Path(tmp_path) / "designs" / design_id / "revisions" / rev
        rev_dir.mkdir(parents=True, exist_ok=True)
        snapshot = Design(id=design_id, revision_id=rev, name="t", script="")
        (rev_dir / "build.json").write_text(json.dumps(Build(revision_id=rev, mesh_hash="x").model_dump(mode="json")))
        (rev_dir / "design.json").write_text(json.dumps(snapshot.model_dump(mode="json")))
        ts = 1_700_000_000 + i
        os.utime(rev_dir / "build.json", (ts, ts))

    deleted = store_module.prune_revisions(design_id, keep_last=2)
    revisions_dir = Path(store_module._design_dir(design_id)) / "revisions"
    remaining = {p.name for p in revisions_dir.iterdir() if p.is_dir()}
    # keep_last=2 retains the 2 newest by mtime (head + orphan-4); the other
    # 4 orphans have no parent linkage and aren't pinned, so they're dropped.
    assert remaining == {"head", "orphan-4"}
    assert deleted == 4


def test_prune_zero_is_noop(store_with_chain):
    store_module, design_id, chain = store_with_chain
    deleted = store_module.prune_revisions(design_id, keep_last=0)
    assert deleted == 0
