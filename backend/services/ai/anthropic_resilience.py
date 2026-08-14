"""Credential selection and bounded resilience for Anthropic calls.

Customer-provided API keys are request-scoped: callers pass them in memory and
this module returns only a one-way credential scope for circuit isolation.  It
never persists or logs the key.
"""

from __future__ import annotations

import hashlib
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterable


TRANSIENT_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504, 529}
_MAX_CIRCUITS = 256


class InvalidAnthropicApiKey(ValueError):
    """A BYOK header was present but did not look like an Anthropic API key."""


class AnthropicCircuitOpen(RuntimeError):
    """Calls are temporarily blocked after repeated transient failures."""

    status_code = 503
    request_id = None


@dataclass(frozen=True)
class AnthropicCredentials:
    api_key: str = field(repr=False)
    billing_source: str
    circuit_scope: str


@dataclass(frozen=True)
class AnthropicCallResult:
    response: Any
    model: str
    attempts: int
    fallback_used: bool


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0


_circuit_lock = threading.Lock()
_circuits: OrderedDict[str, _CircuitState] = OrderedDict()


def resolve_anthropic_credentials(
    request_api_key: str | None,
    platform_api_key: str,
    *,
    allow_platform_billing: bool = True,
) -> AnthropicCredentials | None:
    """Select BYOK when the request explicitly supplies it, otherwise platform.

    An invalid or blank BYOK value never falls back to the platform account;
    that would silently charge Pulsai contrary to the user's billing choice.
    """
    if request_api_key is not None:
        key = request_api_key.strip()
        if not key or len(key) > 512 or not key.startswith("sk-ant-"):
            raise InvalidAnthropicApiKey("Invalid customer Anthropic API key.")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return AnthropicCredentials(
            api_key=key,
            billing_source="customer_byok",
            circuit_scope=f"byok:{digest}",
        )
    if allow_platform_billing and platform_api_key:
        return AnthropicCredentials(
            api_key=platform_api_key,
            billing_source="platform",
            circuit_scope="platform",
        )
    return None


def is_transient_anthropic_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in TRANSIENT_STATUS_CODES:
        return True
    return exc.__class__.__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
    }


def _retry_after_seconds(exc: Exception, now: float) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(raw)).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
        return max(0.0, retry_at - now)


def retry_delay_seconds(
    exc: Exception,
    retry_index: int,
    *,
    base_delay_s: float,
    max_delay_s: float,
    now: float | None = None,
    random_fn: Callable[[], float] = random.random,
) -> float:
    current_time = time.time() if now is None else now
    retry_after = _retry_after_seconds(exc, current_time)
    if retry_after is not None:
        return min(max_delay_s, retry_after)
    exponential = min(max_delay_s, base_delay_s * (2 ** max(0, retry_index)))
    # Equal jitter avoids synchronized retries while keeping a useful floor.
    return exponential * (0.5 + 0.5 * random_fn())


def _circuit_key(scope: str, model: str) -> str:
    return f"{scope}:{model}"


def _before_call(key: str, *, now: float) -> None:
    with _circuit_lock:
        state = _circuits.get(key)
        if state is None:
            return
        _circuits.move_to_end(key)
        if state.opened_until > now:
            raise AnthropicCircuitOpen("Anthropic circuit is temporarily open.")
        if state.opened_until:
            state.failures = 0
            state.opened_until = 0.0


def _record_success(key: str) -> None:
    with _circuit_lock:
        _circuits.pop(key, None)


def _record_transient_failure(
    key: str,
    *,
    failure_threshold: int,
    cooldown_s: float,
    now: float,
) -> None:
    with _circuit_lock:
        state = _circuits.setdefault(key, _CircuitState())
        state.failures += 1
        if state.failures >= max(1, failure_threshold):
            state.opened_until = now + max(0.0, cooldown_s)
        _circuits.move_to_end(key)
        while len(_circuits) > _MAX_CIRCUITS:
            _circuits.popitem(last=False)


def call_messages_with_resilience(
    client: Any,
    *,
    primary_model: str,
    fallback_models: Iterable[str] = (),
    request_kwargs: dict[str, Any],
    circuit_scope: str,
    max_attempts: int = 3,
    base_delay_s: float = 0.5,
    max_delay_s: float = 8.0,
    failure_threshold: int = 3,
    cooldown_s: float = 30.0,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    random_fn: Callable[[], float] = random.random,
) -> AnthropicCallResult:
    """Call Messages with bounded retries, model fallback, and a circuit breaker."""
    models: list[str] = []
    for model in (primary_model, *fallback_models):
        normalized = model.strip()
        if normalized and normalized not in models:
            models.append(normalized)
    if not models:
        raise ValueError("At least one Anthropic model is required.")

    attempts = 0
    last_error: Exception | None = None
    # A bad environment value must not turn a single user request into an
    # unbounded paid retry loop.
    configured_attempts = min(5, max(1, max_attempts))
    for model_index, model in enumerate(models):
        key = _circuit_key(circuit_scope, model)
        try:
            _before_call(key, now=clock())
        except AnthropicCircuitOpen as exc:
            last_error = exc
            continue

        for attempt_index in range(configured_attempts):
            attempts += 1
            try:
                response = client.messages.create(model=model, **request_kwargs)
            except Exception as exc:  # noqa: BLE001 - SDK exposes typed runtime errors
                last_error = exc
                if not is_transient_anthropic_error(exc):
                    raise
                if attempt_index + 1 < configured_attempts:
                    sleeper(
                        retry_delay_seconds(
                            exc,
                            attempt_index,
                            base_delay_s=base_delay_s,
                            max_delay_s=max_delay_s,
                            now=clock(),
                            random_fn=random_fn,
                        )
                    )
                    continue
                _record_transient_failure(
                    key,
                    failure_threshold=failure_threshold,
                    cooldown_s=cooldown_s,
                    now=clock(),
                )
                break
            else:
                _record_success(key)
                return AnthropicCallResult(
                    response=response,
                    model=model,
                    attempts=attempts,
                    fallback_used=model_index > 0,
                )

    if last_error is not None:
        raise last_error
    raise AnthropicCircuitOpen("No Anthropic model is currently available.")


def reset_circuits_for_tests() -> None:
    with _circuit_lock:
        _circuits.clear()


__all__ = [
    "AnthropicCallResult",
    "AnthropicCircuitOpen",
    "AnthropicCredentials",
    "InvalidAnthropicApiKey",
    "call_messages_with_resilience",
    "is_transient_anthropic_error",
    "reset_circuits_for_tests",
    "resolve_anthropic_credentials",
    "retry_delay_seconds",
]
