"""Retrieval of similar historical cases.

Retrieval supplies evidence. It never decides an outcome: the Policy gate
reads the category master, and nothing in this module can change a policy
flag. A retrieved case that was auto-closed in the past does not make the
present case auto-closable.

Three ranking methods, reported on every result so the officer can see how the
evidence was found:

* pgvector-knn      - Postgres with embeddings present (production path)
* in-memory-cosine  - embeddings present but not on Postgres (tests, SQLite)
* keyword-overlap   - no embeddings loaded yet; honest lexical fallback
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import is_postgres
from app.llm.provider import tokenize
from app.models import GrievanceHistory
from app.rag.embeddings import cosine_similarity, embed_text, embedding_method

PGVECTOR_KNN = "pgvector-knn"
IN_MEMORY_COSINE = "in-memory-cosine"
KEYWORD_OVERLAP = "keyword-overlap"


@dataclass(frozen=True)
class RetrievedCase:
    grievance_id: str
    complaint_text: str
    category_id: str
    department_id: str
    taluka: str
    locality: str
    status: str
    resolution_text: str | None
    resolution_days: int | None
    citizen_feedback: str
    similarity: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetrievalResult:
    """Evidence plus how it was obtained. Never an instruction."""

    cases: list[RetrievedCase]
    method: str
    rationale: str

    @property
    def case_ids(self) -> list[str]:
        return [c.grievance_id for c in self.cases]

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "rationale": self.rationale,
            "cases": [c.as_dict() for c in self.cases],
            "evidence_only": True,
        }


def _to_case(row: GrievanceHistory, similarity: float) -> RetrievedCase:
    return RetrievedCase(
        grievance_id=row.grievance_id,
        complaint_text=row.complaint_text,
        category_id=row.category_id,
        department_id=row.department_id,
        taluka=row.broad_location_taluka,
        locality=row.broad_location_locality,
        status=row.status,
        resolution_text=row.resolution_text,
        resolution_days=row.resolution_days,
        citizen_feedback=row.citizen_feedback,
        similarity=round(float(similarity), 4),
    )


def _keyword_rank(
    session: Session, text: str, *, k: int, category_id: str | None
) -> RetrievalResult:
    stmt = select(GrievanceHistory)
    if category_id:
        stmt = stmt.where(GrievanceHistory.category_id == category_id)
    rows = list(session.scalars(stmt))
    query_tokens = set(tokenize(text))
    scored = []
    for row in rows:
        row_tokens = set(tokenize(row.complaint_text))
        if not row_tokens:
            continue
        overlap = len(query_tokens & row_tokens)
        if overlap:
            scored.append((overlap / len(query_tokens | row_tokens), row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    cases = [_to_case(row, score) for score, row in scored[:k]]
    return RetrievalResult(
        cases=cases,
        method=KEYWORD_OVERLAP,
        rationale=(
            f"No embeddings were available, so the {len(cases)} case(s) shown "
            f"were ranked by word overlap. Treat them as weaker evidence than "
            f"semantic matches."
        ),
    )


def retrieve_similar(
    session: Session,
    text: str,
    *,
    k: int = 5,
    category_id: str | None = None,
) -> RetrievalResult:
    """Return the k most similar historical cases as supporting evidence."""
    has_embeddings = session.scalar(
        select(GrievanceHistory.grievance_id)
        .where(GrievanceHistory.embedding.isnot(None))
        .limit(1)
    )
    if not has_embeddings:
        return _keyword_rank(session, text, k=k, category_id=category_id)

    query_vector = embed_text(text)

    if is_postgres():
        stmt = select(
            GrievanceHistory,
            GrievanceHistory.embedding.cosine_distance(query_vector).label("distance"),
        ).where(GrievanceHistory.embedding.isnot(None))
        if category_id:
            stmt = stmt.where(GrievanceHistory.category_id == category_id)
        rows = session.execute(stmt.order_by("distance").limit(k)).all()
        cases = [_to_case(row[0], 1.0 - float(row[1])) for row in rows]
        method = PGVECTOR_KNN
    else:
        stmt = select(GrievanceHistory).where(GrievanceHistory.embedding.isnot(None))
        if category_id:
            stmt = stmt.where(GrievanceHistory.category_id == category_id)
        # Defensive: a partially embedded table is a real state during the
        # backfill, and an empty vector must never be scored as evidence.
        scored = [
            (cosine_similarity(query_vector, row.embedding), row)
            for row in session.scalars(stmt)
            if row.embedding
        ]
        if not scored:
            return _keyword_rank(session, text, k=k, category_id=category_id)
        scored.sort(key=lambda pair: pair[0], reverse=True)
        cases = [_to_case(row, score) for score, row in scored[:k]]
        method = IN_MEMORY_COSINE

    return RetrievalResult(
        cases=cases,
        method=method,
        rationale=(
            f"Top {len(cases)} historical case(s) by {method} using "
            f"{embedding_method()} embeddings. Supporting evidence only; the "
            f"outcome is decided by the category policy, not by these cases."
        ),
    )
