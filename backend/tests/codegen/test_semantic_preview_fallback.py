from __future__ import annotations

from types import SimpleNamespace

from services.codegen.runner.host import _semantic_face_scene


class _GoodFace:
    geom_type = "Plane"
    area = 1.0

    def center(self):
        return SimpleNamespace(X=0.0, Y=0.0, Z=0.0)

    def normal_at(self):
        return SimpleNamespace(X=0.0, Y=0.0, Z=1.0)


class _BadFace:
    geom_type = "Plane"
    area = 1.0

    def center(self):
        raise RuntimeError("classification failed")


class _Shape:
    def faces(self):
        return [_GoodFace(), _BadFace()]


def test_incomplete_semantic_scene_falls_back_to_full_mesh() -> None:
    scene, selection_map = _semantic_face_scene(_Shape(), {})
    assert scene is None
    assert selection_map == {}
