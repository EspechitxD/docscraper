"""Embeddings locais. O vetor padrão não é um modelo neural."""

from __future__ import annotations

import math
import re
import unicodedata
import zlib

DIMENSIONS = 256
MODEL_ID = "cpmh-hash-v1"

_TOKEN = re.compile(r"[\wÀ-ÿ]{2,}", re.UNICODE)
_STOP = {
    "de", "da", "do", "das", "dos", "que", "qual", "quais", "como", "para", "com", "sem",
    "uma", "uns", "umas", "por", "em", "no", "na", "nos", "nas", "ao", "aos", "ou", "se",
    "os", "as", "um", "foi", "são", "ser", "ter", "não", "mais", "sobre", "entre", "este",
    "esta", "esse", "essa", "seu", "sua", "the", "and", "for", "neste", "nesta", "nesse",
    "nessa", "deste", "desta", "desse", "dessa", "disso", "isto", "isso", "onde", "quando",
}


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [token for token in _TOKEN.findall(normalized) if token not in _STOP]


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    tokens = tokenize(text)
    for token in tokens:
        digest = zlib.crc32(token.encode("utf-8"))
        vector[digest % DIMENSIONS] += 1.0
        vector[(digest >> 8) % DIMENSIONS] += 0.35
    compact = " ".join(tokens)
    for index in range(max(len(compact) - 2, 0)):
        digest = zlib.crc32(compact[index : index + 3].encode("utf-8"))
        vector[digest % DIMENSIONS] += 0.15
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
