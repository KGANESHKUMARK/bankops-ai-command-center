"""Model gateway: OpenAI-compatible provider with retries/jitter, circuit breaker, validation, secrets hygiene."""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from pydantic import SecretStr

from app.ai import gateway as gw
from app.ai.gateway import ModelGateway, ProviderError
from app.ai.prompts import PROMPTS
from app.ai.providers.mock import MockLLMProvider
from app.ai.providers.openai_compat import OpenAICompatibleProvider
from app.core.config import InsecureConfigurationError, Settings, validate_startup_settings

KEY = "sk-test-SUPERSECRET-000000000000"
VALID = {"summary": "s", "hypotheses": [], "abstained": True, "abstention_reason": "none", "conflicting_evidence": False}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(gw.time, "sleep", lambda _s: None)


def live_settings(**kw) -> Settings:  # type: ignore[no-untyped-def]
    base = dict(_env_file=None, llm_provider="openai_compatible", llm_base_url="https://llm.example.invalid/v1",
                llm_api_key=SecretStr(KEY), llm_model="gpt-4o-mini", llm_max_retries=2, llm_circuit_breaker_threshold=3)
    base.update(kw)
    return Settings(**base)


def gateway_with(handler, **kw) -> tuple[ModelGateway, list[httpx.Request]]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request, len(seen))

    s = live_settings(**kw)
    provider = OpenAICompatibleProvider(s, client=httpx.Client(transport=httpx.MockTransport(wrapped)))
    return ModelGateway(s, provider), seen


def ok(content: str, usage: bool = True) -> httpx.Response:
    body = {"choices": [{"message": {"content": content}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 120, "completion_tokens": 30}
    return httpx.Response(200, json=body)


def call(g: ModelGateway):  # type: ignore[no-untyped-def]
    return g.generate(PROMPTS["diagnosis"], context_text="ctx", context={}, budget_remaining=100000)


def test_success_parses_schema_and_reports_usage_and_cost() -> None:
    g, seen = gateway_with(lambda r, n: ok(json.dumps(VALID)))
    res = call(g)
    assert res.output.abstained is True and res.input_tokens == 120 and not res.tokens_estimated and not res.is_mock
    assert res.estimated_cost_usd > 0
    sent = json.loads(seen[0].content)
    assert sent["temperature"] == 0 and sent["response_format"] == {"type": "json_object"} and sent["model"] == "gpt-4o-mini"


def test_transient_errors_retried_with_bound() -> None:
    g, seen = gateway_with(lambda r, n: httpx.Response(503) if n < 3 else ok(json.dumps(VALID)))
    assert call(g).attempts == 3 and len(seen) == 3


def test_timeouts_exhaust_retries_with_sanitized_code() -> None:
    def boom(request, n):  # type: ignore[no-untyped-def]
        raise httpx.ReadTimeout("timed out", request=request)

    g, seen = gateway_with(boom)
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert exc.value.code == "provider_timeout" and len(seen) == 3


def test_client_errors_not_retried() -> None:
    g, seen = gateway_with(lambda r, n: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert exc.value.code == "provider_http_400" and len(seen) == 1


def test_malformed_output_gets_one_repair_attempt_then_fails() -> None:
    g, seen = gateway_with(lambda r, n: ok("Sure! Here is my answer: renderer broken"))
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert exc.value.code == "malformed_output" and len(seen) == 2


def test_repair_attempt_can_succeed_and_code_fences_are_tolerated() -> None:
    g, _ = gateway_with(lambda r, n: ok("oops") if n == 1 else ok("```json\n" + json.dumps(VALID) + "\n```"))
    assert call(g).output.summary == "s"


def test_schema_violation_rejected() -> None:
    bad = {**VALID, "hypotheses": [{"id": "H1", "title": "t", "confidence": 7}]}
    g, _ = gateway_with(lambda r, n: ok(json.dumps(bad)))
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert exc.value.code == "malformed_output"


def test_circuit_breaker_opens_and_fails_fast() -> None:
    g, seen = gateway_with(lambda r, n: httpx.Response(500), llm_max_retries=0)
    for _ in range(3):
        with pytest.raises(ProviderError):
            call(g)
    calls_before = len(seen)
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert exc.value.code == "circuit_open" and len(seen) == calls_before and g.status()["circuit_breaker"] == "open"


def test_token_budget_checked_before_call() -> None:
    g, seen = gateway_with(lambda r, n: ok(json.dumps(VALID)))
    with pytest.raises(ProviderError) as exc:
        g.generate(PROMPTS["diagnosis"], context_text="x" * 10000, context={}, budget_remaining=100)
    assert exc.value.code == "token_budget_exceeded" and not seen


def test_unapproved_model_is_refused() -> None:
    with pytest.raises(ProviderError) as exc:
        OpenAICompatibleProvider(live_settings(llm_model="some-unvetted-model"))
    assert exc.value.code == "model_not_approved"
    with pytest.raises(InsecureConfigurationError):
        validate_startup_settings(live_settings(llm_model="some-unvetted-model"))


def test_api_key_never_logged_or_in_errors(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    g, seen = gateway_with(lambda r, n: httpx.Response(503) if n == 1 else httpx.Response(401))
    with pytest.raises(ProviderError) as exc:
        call(g)
    assert KEY not in str(exc.value) and KEY not in caplog.text
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"  # sent only in the outbound header


def test_mock_provider_is_labeled_and_offline() -> None:
    g = ModelGateway(Settings(_env_file=None), MockLLMProvider())
    res = g.generate(PROMPTS["diagnosis"], context_text="c",
                     context={"incident": {"category": "x"}, "retrieval": {"sufficient": False, "reason": "none"}},
                     budget_remaining=100000)
    assert res.is_mock and res.estimated_cost_usd == 0.0 and g.mode == "MOCK" and res.output.abstained
