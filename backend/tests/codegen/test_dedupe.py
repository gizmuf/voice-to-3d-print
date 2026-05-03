"""Feature-graph dedup keeps one row per logical feature."""

from services.codegen.engine import _dedupe_named_features
from services.codegen.models import NamedFeature


def test_block_wins_over_classifier_for_same_id():
    features = [
        NamedFeature(name="ring", kind="Part", source=""),
        NamedFeature(name="ring", kind="block", source="code goes here"),
    ]
    out = _dedupe_named_features(features)
    assert len(out) == 1
    assert out[0].kind == "block"
    assert out[0].source == "code goes here"


def test_classifier_first_then_block_still_merges_to_block():
    """Insertion order shouldn't change which view wins."""
    features = [
        NamedFeature(name="ring", kind="block", source="code"),
        NamedFeature(name="ring", kind="Part", source=""),
    ]
    out = _dedupe_named_features(features)
    assert len(out) == 1
    assert out[0].source == "code"


def test_within_kind_dedupe_unions_metadata():
    a = NamedFeature(
        name="hole",
        kind="block",
        source="",
        parameters_used=["x"],
        user_words=["hole"],
    )
    b = NamedFeature(
        name="hole",
        kind="block",
        source="real source",
        parameters_used=["y"],
        user_words=["mounting"],
    )
    out = _dedupe_named_features([a, b])
    assert len(out) == 1
    assert out[0].source == "real source"
    assert out[0].parameters_used == ["x", "y"]
    assert "hole" in out[0].user_words and "mounting" in out[0].user_words


def test_different_ids_stay_distinct():
    out = _dedupe_named_features(
        [
            NamedFeature(name="hole", source=""),
            NamedFeature(name="boss", source=""),
        ]
    )
    assert {f.id for f in out} == {"hole", "boss"}


def test_classifier_only_kept_when_no_block():
    out = _dedupe_named_features(
        [
            NamedFeature(name="ring", kind="Part", source=""),
        ]
    )
    assert len(out) == 1
    assert out[0].kind == "Part"
