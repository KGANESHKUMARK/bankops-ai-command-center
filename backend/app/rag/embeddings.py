"""Embedding provider abstraction.

- `HashingEmbedder` (default, offline): deterministic signed feature hashing of
  stemmed unigrams and bigrams, sublinear TF weighting, L2-normalized. It is a
  lexical-semantic approximation, not a neural model; it needs no network or key.
- `OpenAICompatibleEmbedder`: calls `POST {base_url}/embeddings` on any
  OpenAI-compatible endpoint configured via environment variables.
"""

from __future__ import annotations

import hashlib
import math
import random
import time
from collections import Counter
from typing import Protocol

import httpx
import numpy as np

from app.core.config import Settings
from app.rag.text import tokenize


class EmbeddingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Embedder(Protocol):
    provider: str
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    provider = "hashing"
    model = "feature-hashing-v1"

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _vector(self, text: str) -> list[float]:
        tokens = tokenize(text)
        features = Counter(tokens)
        features.update({f"{a}_{b}": 0.5 for a, b in zip(tokens, tokens[1:], strict=False)})
        vec = np.zeros(self.dim, dtype=np.float32)
        for feature, count in features.items():
            digest = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
            sign = 1.0 if digest >> 63 else -1.0
            vec[digest % self.dim] += sign * (1.0 + math.log(1.0 + count))
        norm = float(np.linalg.norm(vec))
        return (vec / norm).tolist() if norm > 0 else vec.tolist()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class OpenAICompatibleEmbedder:
    provider = "openai_compatible"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.embedding_base_url or settings.embedding_api_key is None:
            raise EmbeddingError("embedding_provider_not_configured")
        self.model = settings.embedding_model
        self.dim = settings.embedding_dim
        self._url = settings.embedding_base_url.rstrip("/") + "/embeddings"
        self._key = settings.embedding_api_key
        self._retries = settings.llm_max_retries
        self._client = client or httpx.Client(timeout=httpx.Timeout(settings.llm_timeout_seconds))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            out.extend(self._embed_batch(texts[start : start + 64]))
        return out

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch, "dimensions": self.dim}
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.post(self._url, json=payload, headers=headers)
            except httpx.TimeoutException:
                code = "embedding_timeout"
            except httpx.HTTPError:
                code = "embedding_network_error"
            else:
                if resp.status_code == 200:
                    data = sorted(resp.json().get("data", []), key=lambda d: d.get("index", 0))
                    vectors = [d["embedding"] for d in data]
                    if len(vectors) != len(batch) or any(len(v) != self.dim for v in vectors):
                        raise EmbeddingError("embedding_dimension_mismatch")
                    return vectors
                code = f"embedding_http_{resp.status_code}"
                if resp.status_code < 500 and resp.status_code != 429:
                    raise EmbeddingError(code)
            if attempt < self._retries:
                time.sleep(min(4.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))
        raise EmbeddingError(code)


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbedder(settings)
    return HashingEmbedder(settings.embedding_dim)
