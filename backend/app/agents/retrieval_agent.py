"""Retrieval Agent.

Fetches similar past cases and passes them on as evidence with a rationale.

It deliberately returns no recommendation. Downstream, the Policy gate reads
the category master and ignores this payload entirely, so a historical case
that happened to be auto-closed can never drag a sensitive case into
automation.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.observability.trace import RETRIEVAL_SPAN, record, span
from app.rag.retrieval import retrieve_similar


def run_retrieval(session: Session, state: PipelineState, *, k: int = 5) -> PipelineState:
    draft = state.get("draft") or {}
    query = draft.get("description") or state.get("raw_text", "")
    category_id = draft.get("category_id")

    with span(RETRIEVAL_SPAN, query_characters=len(query), category_id=category_id) as current:
        result = retrieve_similar(session, query, k=k, category_id=category_id)
        record(
            current,
            method=result.method,
            retrieved_case_ids=result.case_ids,
            top_similarity=result.cases[0].similarity if result.cases else None,
        )

    state["evidence"] = result.as_dict()
    state["retrieved_case_ids"] = result.case_ids
    return state
