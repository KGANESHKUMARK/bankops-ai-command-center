"""BM25 keyword scoring over an (already authorization-filtered) candidate set."""

from __future__ import annotations

import math
from collections import Counter

from app.rag.text import tokenize


def bm25_scores(query: str, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> list[float]:
    q_terms = set(tokenize(query))
    if not q_terms or not documents:
        return [0.0] * len(documents)
    tokenized = [tokenize(d) for d in documents]
    n = len(tokenized)
    avgdl = sum(len(t) for t in tokenized) / n or 1.0
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks) & q_terms)
    scores: list[float] = []
    for toks in tokenized:
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for term in q_terms:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf[term] * (k1 + 1)) / (tf[term] + k1 * (1 - b + b * dl / avgdl))
        scores.append(score)
    return scores


def term_coverage(query: str, document: str) -> float:
    """Fraction of distinct query terms present in the document (used by the lexical reranker)."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return 0.0
    return len(q_terms & set(tokenize(document))) / len(q_terms)
