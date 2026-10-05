"""OpenAI-compatible chat-completions provider (any endpoint implementing /chat/completions)."""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.gateway import ProviderError, RawCompletion
from app.core.config import Settings
from app.rag.text import estimate_tokens


class OpenAICompatibleProvider:
    name = "openai_compatible"
    is_mock = False

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.llm_base_url or settings.llm_api_key is None:
            raise ProviderError("provider_not_configured")
        if settings.llm_model not in settings.llm_approved_models:
            raise ProviderError("model_not_approved")
        self.model = settings.llm_model
        self._url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        self._key = settings.llm_api_key
        timeout = httpx.Timeout(settings.llm_timeout_seconds, connect=min(10.0, settings.llm_timeout_seconds))
        self._client = client or httpx.Client(timeout=timeout)

    def complete(
        self, *, system: str, user: str, prompt_id: str, context: dict[str, Any], max_tokens: int
    ) -> RawCompletion:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = self._client.post(
                self._url, json=payload, headers={"Authorization": f"Bearer {self._key.get_secret_value()}"}
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("provider_timeout", transient=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("provider_network_error", transient=True) from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"provider_http_{resp.status_code}", transient=True)
        if resp.status_code != 200:
            raise ProviderError(f"provider_http_{resp.status_code}")
        try:
            body = resp.json()
            text = body["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider_bad_response") from exc
        usage = body.get("usage") or {}
        if "prompt_tokens" in usage and "completion_tokens" in usage:
            return RawCompletion(text, int(usage["prompt_tokens"]), int(usage["completion_tokens"]), False)
        return RawCompletion(text, estimate_tokens(system + user), estimate_tokens(text), True)
