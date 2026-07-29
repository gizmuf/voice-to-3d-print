from services.deepgram_stt import _request_params


def test_polish_nova_3_uses_keyterms_without_english_measurements() -> None:
    params = _request_params(model="nova-3", language="pl")

    assert params["language"] == "pl"
    assert "keyterm" in params
    assert "keywords" not in params
    assert "measurements" not in params


def test_nova_2_uses_legacy_keywords() -> None:
    params = _request_params(model="nova-2", language="pl")

    assert "keywords" in params
    assert "keyterm" not in params


def test_english_keeps_measurement_formatting() -> None:
    params = _request_params(model="nova-3", language="en")

    assert params["measurements"] == "true"
