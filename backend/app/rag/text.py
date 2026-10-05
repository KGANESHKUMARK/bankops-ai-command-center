"""Text normalization and a small deterministic tokenizer used by embeddings and BM25."""

from __future__ import annotations

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_WORD = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_DOUBLE = re.compile(r"([b-df-hj-km-pqrtv-z])\1$")

STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by", "can", "could", "did", "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in", "into", "is", "it", "its", "of", "on", "or", "our", "should", "so", "than", "that", "the", "their", "then", "there", "these", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with", "would", "you", "your", "via", "per", "not", "no", "any", "all", "also", "may", "must"]
)

_SUFFIXES = ("ingly", "edly", "ments", "ment", "ings", "ing", "ures", "ure", "ers", "er", "ed", "es", "s", "ly")


def normalize_text(text: str) -> str:
    """NFKC-normalize, strip control/bidi characters and collapse excessive whitespace."""
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def stem(word: str) -> str:
    if len(word) <= 4 or word.isdigit():
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return _DOUBLE.sub(r"\1", word)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD.findall(text.lower()):
        parts = [raw, *re.split(r"[-_]", raw)] if ("-" in raw or "_" in raw) else [raw]
        for part in parts:
            if part and part not in STOPWORDS and len(part) > 1:
                tokens.append(stem(part))
    return tokens


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 characters per token) used when providers report no usage."""
    return max(1, len(text) // 4)
