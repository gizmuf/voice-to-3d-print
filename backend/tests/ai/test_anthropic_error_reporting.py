from services.ai.agent_v2 import _anthropic_failure_payload


class _AnthropicError(Exception):
    status_code = 400
    request_id = "req_test_123"


def test_anthropic_validation_error_is_safe_and_traceable() -> None:
    payload = _anthropic_failure_payload(
        _AnthropicError("messages.7.content.0.thinking.thinking: Field required")
    )

    assert payload == {
        "code": "ai_invalid_request",
        "message": (
            "Nie udało się dokończyć tej wiadomości. Projekt pozostał bez zmian — "
            "spróbuj wysłać ją ponownie."
        ),
        "request_id": "req_test_123",
        "retryable": True,
    }
    assert "thinking" not in payload["message"]


def test_anthropic_rate_limit_has_a_distinct_code() -> None:
    error = _AnthropicError("rate limit")
    error.status_code = 429

    payload = _anthropic_failure_payload(error)

    assert payload["code"] == "ai_rate_limited"
    assert payload["retryable"] is True

