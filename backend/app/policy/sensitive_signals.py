"""A second, independent signal that a complaint may be sensitive.

Why this exists: the sensitive guard trusts the category. When the classifier
is wrong in the dangerous direction — filing a sparking live wire as "footpath
damage" — nothing downstream objects, because the chosen category is genuinely
not sensitive.

The first backstop is the retrieved evidence (see apply_precautionary_hold),
but that depends on the embedding actually finding a sensitive neighbour. With
semantic embeddings it does; with the offline lexical fallback it does not,
because "live wire sparking" shares no words with "damaged electrical cable
hanging close to the public path".

So this module adds a signal that needs no embedding at all: match the
complaint against the *category master's own wording* for sensitive
categories.

No keyword list is hardcoded. The terms are derived from whatever the loaded
CSV calls its sensitive categories, and only **distinctive** terms count —
words that appear in at most two categories across the whole master. That
keeps "public", "service" and "concern" from firing on everything while
letting "wire", "harassment" and "child" do their job. Swap the CSV and the
vocabulary follows.
"""
from __future__ import annotations

import os
from collections import Counter
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.provider import tokenize
from app.models import CategoryMaster

#: A term counts as distinctive if at most this many categories use it.
MAX_CATEGORIES_PER_TERM = int(os.environ.get("SENSITIVE_TERM_MAX_SPREAD", "2"))


def distinctive_sensitive_terms(session: Session) -> dict[str, set[str]]:
    """Terms that point at one sensitive category and few others.

    Built from category + subcategory wording in the loaded master.
    """
    rows = list(session.scalars(select(CategoryMaster)))
    vocab: dict[str, set[str]] = {}
    spread: Counter[str] = Counter()

    for row in rows:
        terms = set(tokenize(f"{row.category} {row.subcategory}"))
        vocab[row.category_id] = terms
        for term in terms:
            spread[term] += 1

    distinctive: dict[str, set[str]] = {}
    for row in rows:
        if not row.identity_hiding and not row.sensitive:
            continue
        keep = {
            term
            for term in vocab[row.category_id]
            if spread[term] <= MAX_CATEGORIES_PER_TERM
        }
        if keep:
            distinctive[row.category_id] = keep
    return distinctive


def sensitive_wording_matches(session: Session, text: str) -> list[dict[str, Any]]:
    """Sensitive categories whose distinctive wording appears in the text."""
    tokens = set(tokenize(text))
    if not tokens:
        return []

    matches: list[dict[str, Any]] = []
    for category_id, terms in distinctive_sensitive_terms(session).items():
        hit = tokens & terms
        if hit:
            matches.append(
                {
                    "category_id": category_id,
                    "terms": sorted(hit),
                    # Reported so the officer can see how thin or strong the
                    # signal was, rather than just that something fired.
                    "strength": round(len(hit) / len(terms), 3),
                }
            )
    matches.sort(key=lambda m: m["strength"], reverse=True)
    return matches
