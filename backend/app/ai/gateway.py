"""Provider-independent model gateway.

Responsibilities: provider selection (explicit configuration only - never a silent
switch), strict timeouts, bounded retries with jitter for transient errors only,
a circuit breaker, token-budget enforcement, JSON/schema validation with a single
bounded repair attempt, and metering (latency, tokens, estimated cost).
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.prompts import PromptTemplate
from app.core.config import Settings
from app.core.logging import get_logger
from app.rag.text import estimate_tokens

log = get_logger("ai.gateway")
T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """Sanitized provider failure. `code` is safe to store and display."""

    def __init__(self, code: str, *, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


@dataclass
class RawCompletion:
    text: str
    input_tokens: int
    output_tokens: int
    tokens_estimated: bool


class LLMProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def complete(
        self, *, system: str, user: str, prompt_id: str, context: dict[str, Any], max_tokens: int
    ) -> RawCompletion: ...


@dataclass
class LLMResult:
    output: BaseModel
    provider: str
    model: str
    prompt_id: str
    prompt_version: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    tokens_estimated: bool
    is_mock: bool
    attempts: int
    estimated_cost_usd: float


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown_seconds: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._opened_at is None:
                return "closed"
            return "half_open" if time.monotonic() - self._opened_at >= self.cooldown else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.threshold:
                self._opened_at = time.monotonic()


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating Markdown code fences around it."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(cleaned)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise json.JSONDecodeError("not an object", cleaned, 0)
    return data


class ModelGateway:
    def __init__(self, settings: Settings, provider: LLMProvider) -> None:
        self.settings = settings
        self.provider = provider
        self.breaker = CircuitBreaker(
            settings.llm_circuit_breaker_threshold, settings.llm_circuit_breaker_cooldown_seconds
        )

    @property
    def mode(self) -> str:
        return "MOCK" if self.provider.is_mock else "LIVE"

    def status(self) -> dict[str, Any]:
        return {
            "provider": self.provider.name,
            "model": self.provider.model,
            "mode": self.mode,
            "circuit_breaker": self.breaker.state,
        }

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        if self.provider.is_mock:
            return 0.0
        s = self.settings
        return round(input_tokens / 1000 * s.cost_per_1k_input_tokens + output_tokens / 1000 * s.cost_per_1k_output_tokens, 6)

    def _call_with_retries(self, *, system: str, user: str, prompt_id: str, context: dict[str, Any]) -> tuple[RawCompletion, int]:
        attempts = 0
        max_attempts = 1 if self.provider.is_mock else self.settings.llm_max_retries + 1
        while True:
            attempts += 1
            try:
                raw = self.provider.complete(
                    system=system,
                    user=user,
                    prompt_id=prompt_id,
                    context=context,
                    max_tokens=self.settings.llm_max_output_tokens,
                )
                return raw, attempts
            except ProviderError as exc:
                if not exc.transient or attempts >= max_attempts:
                    raise
                delay = min(8.0, 0.5 * 2 ** (attempts - 1)) + random.uniform(0, 0.3)
                log.warning("transient provider error; retrying", extra={"error_code": exc.code, "attempt": attempts})
                time.sleep(delay)

    def generate(
        self,
        prompt: PromptTemplate,
        *,
        context_text: str,
        context: dict[str, Any],
        budget_remaining: int,
        fault_provider_timeout: bool = False,
    ) -> LLMResult:
        """Generate a schema-validated output or raise `ProviderError` with a sanitized code."""
        system = prompt.system
        user = prompt.render_user(context=context_text)
        estimated_in = estimate_tokens(system) + estimate_tokens(user)
        if estimated_in + self.settings.llm_max_output_tokens // 4 > budget_remaining:
            raise ProviderError("token_budget_exceeded")
        if fault_provider_timeout:
            self.breaker.record_failure()
            raise ProviderError("provider_timeout_injected", transient=True)
        if not self.breaker.allow():
            raise ProviderError("circuit_open")

        started = time.perf_counter()
        total_attempts = 0
        try:
            raw, total_attempts = self._call_with_retries(system=system, user=user, prompt_id=prompt.prompt_id, context=context)
            try:
                output = prompt.output_model.model_validate(parse_json_object(raw.text))
            except (json.JSONDecodeError, ValidationError) as first_error:
                # One bounded repair attempt; the error summary contains no model text.
                kind = "invalid JSON" if isinstance(first_error, json.JSONDecodeError) else "schema violation"
                repair_user = f"{user}\n\nYour previous response was rejected ({kind}). Return ONLY a valid JSON object."
                raw2, extra = self._call_with_retries(system=system, user=repair_user, prompt_id=prompt.prompt_id,
                                                      context={**context, "_repair": True})
                total_attempts += extra
                try:
                    output = prompt.output_model.model_validate(parse_json_object(raw2.text))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise ProviderError("malformed_output") from exc
                raw = RawCompletion(
                    text=raw2.text,
                    input_tokens=raw.input_tokens + raw2.input_tokens,
                    output_tokens=raw.output_tokens + raw2.output_tokens,
                    tokens_estimated=raw.tokens_estimated or raw2.tokens_estimated,
                )
        except ProviderError as exc:
            if exc.code != "malformed_output":
                self.breaker.record_failure()
            raise
        self.breaker.record_success()
        latency = int((time.perf_counter() - started) * 1000)
        return LLMResult(
            output=output,
            provider=self.provider.name,
            model=self.provider.model,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            latency_ms=latency,
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
            tokens_estimated=raw.tokens_estimated,
            is_mock=self.provider.is_mock,
            attempts=total_attempts,
            estimated_cost_usd=self._cost(raw.input_tokens, raw.output_tokens),
        )


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "openai_compatible":
        from app.ai.providers.openai_compat import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    from app.ai.providers.mock import MockLLMProvider

    return MockLLMProvider()
