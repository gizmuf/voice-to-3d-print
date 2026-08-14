from pathlib import Path

import pytest

from config import _env_bool, _env_float, _secret_env


def test_platform_spend_switch_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PULSAI_ALLOW_PLATFORM_AI_SPEND", raising=False)
    assert _env_bool("PULSAI_ALLOW_PLATFORM_AI_SPEND", False) is False

    monkeypatch.setenv("PULSAI_ALLOW_PLATFORM_AI_SPEND", "true")
    assert _env_bool("PULSAI_ALLOW_PLATFORM_AI_SPEND", False) is True


def test_float_environment_value_and_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_RETRY_BASE_DELAY_S", "1.25")
    assert _env_float("ANTHROPIC_RETRY_BASE_DELAY_S", 0.5) == 1.25

    monkeypatch.setenv("ANTHROPIC_RETRY_BASE_DELAY_S", "invalid")
    assert _env_float("ANTHROPIC_RETRY_BASE_DELAY_S", 0.5) == 0.5


def test_secret_file_wins_over_plain_environment(tmp_path: Path, monkeypatch) -> None:
    secret_file = tmp_path / "anthropic"
    secret_file.write_text("file-secret\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "plain-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", str(secret_file))

    assert _secret_env("ANTHROPIC_API_KEY") == "file-secret"


def test_unreadable_configured_secret_file_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "stale-plain-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY_FILE", "/definitely/missing/secret")

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _secret_env("ANTHROPIC_API_KEY")
