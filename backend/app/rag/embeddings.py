"""Embedding generation.

With OPENAI_API_KEY set, embeddings come from the configured model. Without
one, a deterministic local embedding is used so the system still runs offline.

The offline embedding is lexical, not semantic: it hashes tokens into a fixed
vector. It is honest about being weaker, and the retrieval layer reports which
method produced the evidence so an officer is never shown lexical matches
labelled as semantic ones.
"""
from __future__ import annotations

import hashlib
import math
from typing import Sequence

from app.config import settings
from app.llm.provider import tokenize

OFFLINE_METHOD = "offline-lexical-hash"
OPENAI_METHOD = "openai-embedding"


def _hash_embed(text: str, dim: int) -> list[float]:
    """Hash tokens into a fixed-width unit vector.

    Deterministic across runs and processes, which matters because the stored
    history embeddings and a live query embedding must land in the same space.
    """
    vector = [0.0] * dim
    for token in tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def embedding_method() -> str:
    return OPENAI_METHOD if settings.openai_api_key else OFFLINE_METHOD


def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    if not texts:
        return []
    if not settings.openai_api_key:
        return [_hash_embed(t, settings.embedding_dim) for t in texts]

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.embedding_model, input=list(texts)
    )
    return [item.embedding for item in response.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
