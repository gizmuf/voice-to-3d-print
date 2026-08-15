from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import services.ai.agent_v2 as agent_v2
from services.ai.agent_v2 import (
    _accepts_stylized_paramotor,
    _assistant_claims_runtime_unavailable,
    _compact_for_persist,
    _history_has_stale_runtime_failure,
    _organic_paramotor_offer,
    _repair_dangling_tool_uses,
)
from services.codegen.models import Design
from services.ai.anthropic_resilience import (
    AnthropicCircuitOpen,
    InvalidAnthropicApiKey,
    call_messages_with_resilience,
    reset_circuits_for_tests,
    resolve_anthropic_credentials,
)


class AnthropicError(Exception):
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code
        self.request_id = "req_test"
        self.response = type("Response", (), {"headers": headers or {}})()


class FakeMessages:
    def __init__(self, outcomes: list[object]):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes: list[object]):
        self.messages = FakeMessages(outcomes)


@pytest.fixture(autouse=True)
def _reset_circuit_registry() -> None:
    reset_circuits_for_tests()


def test_byok_is_request_scoped_and_repr_redacts_the_key() -> None:
    key = "sk-ant-api03-customer-secret"
    credentials = resolve_anthropic_credentials(key, "sk-ant-platform")

    assert credentials is not None
    assert credentials.api_key == key
    assert credentials.billing_source == "customer_byok"
    assert key not in repr(credentials)
    assert key not in credentials.circuit_scope


def test_reference_image_bytes_are_not_persisted_in_conversation() -> None:
    encoded = "private-image-base64"
    history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": encoded,
                    },
                },
                {"type": "text", "text": "width 80 mm"},
            ],
        }
    ]

    compacted = _compact_for_persist(history)

    assert encoded not in repr(compacted)
    assert "was not persisted" in repr(compacted)


def test_rewrite_source_is_bounded_in_persisted_history() -> None:
    script = "from build123d import *\n" + "Box(1, 1, 1)\n" * 1000
    compacted = _compact_for_persist(
        [{"role": "assistant", "content": [{"type": "tool_use", "id": "tool-1", "name": "rewrite_design", "input": {"script": script}}]}]
    )

    persisted_script = compacted[0]["content"][0]["input"]["script"]
    assert len(persisted_script) < 800
    assert "source truncated" in persisted_script


def test_dangling_tool_use_is_repaired_as_an_error_result() -> None:
    repaired = _repair_dangling_tool_uses(
        [{"role": "assistant", "content": [{"type": "tool_use", "id": "tool-1", "name": "rewrite_design", "input": {}}]}]
    )

    result = repaired[-1]["content"][0]
    assert result["tool_use_id"] == "tool-1"
    assert result["is_error"] is True
    assert "design state is unchanged" in result["content"]


def test_realistic_paramotor_is_offered_a_free_stylized_fallback() -> None:
    offer = _organic_paramotor_offer("Zrób realistyczną figurkę motoparalotniarza 120 mm")

    assert offer is not None
    assert "bez kosztu" in offer
    history = [{"role": "assistant", "content": [{"type": "text", "text": offer}]}]
    assert _accepts_stylized_paramotor("tak", history) is True


def test_historical_runtime_failure_is_detected_after_a_deployment_fix() -> None:
    history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-old",
                    "content": '{"error":"Untrusted Python CAD execution is disabled in this deployment."}',
                    "is_error": True,
                }
            ],
        }
    ]

    assert _history_has_stale_runtime_failure(history) is True


def test_stale_runtime_refusal_requires_a_current_tool_attempt() -> None:
    blocks = [
        {
            "type": "text",
            "text": "Napotykam blokadę infrastruktury; silnik odrzuca teraz każdą modyfikację.",
        }
    ]

    assert _assistant_claims_runtime_unavailable(blocks) is True
    assert _assistant_claims_runtime_unavailable(
        [{"type": "text", "text": "Dopytam o promień zaokrąglenia."}]
    ) is False


def test_stale_runtime_refusal_is_hidden_and_retried_with_a_current_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    design = Design(
        id="design-1",
        revision_id="revision-1",
        name="Olga cage leg",
        script="# @feature: hollow\nresult = None\n# @end\n",
        process="fdm",
    )
    history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool-old",
                    "content": '{"error":"Untrusted Python CAD execution is disabled in this deployment."}',
                    "is_error": True,
                }
            ],
        }
    ]
    responses = iter(
        [
            SimpleNamespace(
                model="claude-test",
                usage=None,
                stop_reason="end_turn",
                content=[
                    SimpleNamespace(
                        type="text",
                        text="Napotykam blokadę infrastruktury; silnik odrzuca teraz każdą modyfikację.",
                    )
                ],
            ),
            SimpleNamespace(
                model="claude-test",
                usage=None,
                stop_reason="tool_use",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="tool-current",
                        name="read_design",
                        input={},
                    )
                ],
            ),
            SimpleNamespace(
                model="claude-test",
                usage=None,
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Bieżący silnik CAD odpowiada.")],
            ),
        ]
    )
    system_calls: list[list[dict]] = []
    executed: list[str] = []
    persisted: list[list[dict]] = []

    monkeypatch.setattr(agent_v2, "get_design", lambda _design_id: design)
    monkeypatch.setattr(agent_v2, "get_build", lambda _design_id: None)
    monkeypatch.setattr(agent_v2, "load_conversation", lambda _design_id: history)
    monkeypatch.setattr(
        agent_v2,
        "save_conversation",
        lambda _design_id, transcript: persisted.append(transcript),
    )
    monkeypatch.setattr(
        agent_v2,
        "resolve_anthropic_credentials",
        lambda *_args, **_kwargs: SimpleNamespace(
            api_key="sk-ant-test",
            billing_source="customer_byok",
            circuit_scope="test",
        ),
    )
    monkeypatch.setattr(agent_v2, "Anthropic", lambda **_kwargs: object())
    monkeypatch.setattr(agent_v2, "maybe_compact_history", lambda transcript, **_kwargs: (transcript, False))

    def fake_call(_client, **kwargs):
        system_calls.append(kwargs["request_kwargs"]["system"])
        response = next(responses)
        return SimpleNamespace(response=response, model=response.model, attempts=1, fallback_used=False)

    monkeypatch.setattr(agent_v2, "call_messages_with_resilience", fake_call)
    monkeypatch.setattr(
        agent_v2,
        "execute_tool",
        lambda name, _payload, _ctx: executed.append(name) or {"ok": True},
    )
    monkeypatch.setattr(agent_v2, "record_tool_call", lambda **_kwargs: None)
    monkeypatch.setattr(agent_v2, "evaluate_spec_compliance", lambda *_args: {"status": "unknown"})
    monkeypatch.setattr(agent_v2, "record_spec_targets", lambda *_args, **_kwargs: False)

    events = "".join(agent_v2.stream_turn("design-1", "spróbuj ponownie"))

    assert "silnik odrzuca teraz" not in events
    assert '"mode": "runtime_recheck"' in events
    assert "odpowiada." in events
    assert executed == ["read_design"]
    assert "Current runtime recovery" not in system_calls[0][1]["text"]
    assert "Current runtime recovery" in system_calls[1][1]["text"]
    assert persisted
    assert "silnik odrzuca teraz" not in repr(persisted[-1])


def test_invalid_explicit_byok_never_falls_back_to_platform_billing() -> None:
    with pytest.raises(InvalidAnthropicApiKey):
        resolve_anthropic_credentials("", "sk-ant-platform")
    with pytest.raises(InvalidAnthropicApiKey):
        resolve_anthropic_credentials("not-an-anthropic-key", "sk-ant-platform")


def test_platform_key_is_ignored_when_platform_billing_is_disabled() -> None:
    credentials = resolve_anthropic_credentials(
        None,
        "sk-ant-platform",
        allow_platform_billing=False,
    )

    assert credentials is None


def test_byok_remains_available_when_platform_billing_is_disabled() -> None:
    credentials = resolve_anthropic_credentials(
        "sk-ant-api03-customer-secret",
        "sk-ant-platform",
        allow_platform_billing=False,
    )

    assert credentials is not None
    assert credentials.billing_source == "customer_byok"


def test_529_retries_with_retry_after_and_then_succeeds() -> None:
    response = object()
    client = FakeClient(
        [
            AnthropicError(529, {"retry-after": "2"}),
            response,
        ]
    )
    sleeps: list[float] = []

    result = call_messages_with_resilience(
        client,
        primary_model="claude-sonnet-5",
        request_kwargs={"messages": []},
        circuit_scope="platform",
        max_attempts=3,
        sleeper=sleeps.append,
        random_fn=lambda: 0.0,
    )

    assert result.response is response
    assert result.attempts == 2
    assert sleeps == [2.0]
    assert [call["model"] for call in client.messages.calls] == [
        "claude-sonnet-5",
        "claude-sonnet-5",
    ]


def test_non_transient_auth_error_is_not_retried_or_fallbacked() -> None:
    client = FakeClient([AnthropicError(401)])

    with pytest.raises(AnthropicError) as caught:
        call_messages_with_resilience(
            client,
            primary_model="claude-sonnet-5",
            fallback_models=["claude-sonnet-4-6"],
            request_kwargs={"messages": []},
            circuit_scope="byok:test",
            max_attempts=3,
            sleeper=lambda _: None,
        )

    assert caught.value.status_code == 401
    assert len(client.messages.calls) == 1


def test_fallback_model_runs_after_primary_exhausts_transient_budget() -> None:
    response = object()
    client = FakeClient([AnthropicError(529), response])

    result = call_messages_with_resilience(
        client,
        primary_model="claude-sonnet-5",
        fallback_models=["claude-sonnet-4-6"],
        request_kwargs={"messages": []},
        circuit_scope="platform",
        max_attempts=1,
        sleeper=lambda _: None,
    )

    assert result.response is response
    assert result.model == "claude-sonnet-4-6"
    assert result.fallback_used is True


def test_retry_budget_is_capped_even_when_configuration_is_excessive() -> None:
    client = FakeClient([AnthropicError(529) for _ in range(5)])

    with pytest.raises(AnthropicError):
        call_messages_with_resilience(
            client,
            primary_model="claude-sonnet-5",
            request_kwargs={"messages": []},
            circuit_scope="platform",
            max_attempts=999,
            sleeper=lambda _: None,
        )

    assert len(client.messages.calls) == 5


def test_circuit_opens_after_repeated_exhausted_transient_calls() -> None:
    clock_value = 100.0
    client = FakeClient([AnthropicError(529), AnthropicError(529)])

    for _ in range(2):
        with pytest.raises(AnthropicError):
            call_messages_with_resilience(
                client,
                primary_model="claude-sonnet-5",
                request_kwargs={"messages": []},
                circuit_scope="platform",
                max_attempts=1,
                failure_threshold=2,
                cooldown_s=30,
                sleeper=lambda _: None,
                clock=lambda: clock_value,
            )

    with pytest.raises(AnthropicCircuitOpen):
        call_messages_with_resilience(
            client,
            primary_model="claude-sonnet-5",
            request_kwargs={"messages": []},
            circuit_scope="platform",
            max_attempts=1,
            failure_threshold=2,
            cooldown_s=30,
            sleeper=lambda _: None,
            clock=lambda: clock_value,
        )

    assert len(client.messages.calls) == 2
