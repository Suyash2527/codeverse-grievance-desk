"""Intake Agent.

Turns a free-text complaint in Marathi, Hindi or English into a structured
draft, and lists what is still missing. It proposes a category; it never
decides an outcome, and it never creates a ticket. A ticket exists only after
the citizen confirms the draft (see the intake session endpoints).

The list of categories handed to the model is read from the loaded master, so
the model chooses from whatever the current CSV contains. No category is named
in a prompt.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.llm.provider import LLMProvider, get_provider
from app.observability.trace import INTAKE_SPAN, record, span
from app.policy.store import list_categories

SYSTEM_PROMPT = """You convert citizen grievances into a structured draft for a
district grievance portal in Maharashtra, India.

The complaint may be in Marathi, Hindi or English, including colloquial or
code-mixed speech. Understand it in its own language.

Rules you must follow:
- Choose category_id ONLY from allowed_categories. If none fits, return null.
- Never decide whether the complaint is valid, and never assign blame or
  liability. You only structure what the citizen said.
- description must be a faithful restatement in English for downstream
  retrieval. Do not add facts the citizen did not state.
- description_original must preserve the citizen's own language.
- missing_details lists the specific fields still needed, as short questions
  in the citizen's language.
- similar_past_cases_for_reference shows how this district classified similar
  complaints before. Use them to choose a category consistently. They tell you
  nothing about what should happen to this case: never infer an outcome,
  a resolution or a priority from them.
- confidence is your own 0..1 certainty in the category choice.

Return a single JSON object and nothing else."""

SCHEMA_HINT = """{
  "category_id": "string from allowed_categories, or null",
  "description": "English restatement",
  "description_original": "restatement in the citizen's language",
  "location": {"taluka": "string or null", "locality": "string or null"},
  "urgency": "LOW | MEDIUM | HIGH | CRITICAL",
  "severity": 0.0,
  "urgency_score": 0.0,
  "affected_population_estimate": 0,
  "missing_details": ["short question"],
  "confidence": 0.0,
  "rationale": "one sentence on why this category"
}

severity is how harmful the reported condition is (0..1).
urgency_score is how time-critical it is (0..1).
affected_population_estimate is how many PEOPLE the citizen says are affected,
as an integer, or 0 if they did not say. It is never a count of complaints."""


def neighbour_evidence(
    session: Session,
    text: str,
    *,
    k: int = 8,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Similar past complaints, used to ground the category *suggestion*.

    The district has already classified 800 complaints by hand. Matching a new
    one against that record is a far better signal than matching its words
    against the category names, which is all a cold classifier can do.

    This is classification support, never policy. Whatever category ends up
    chosen, its Sensitive, Identity-Hiding and SLA values are read from the
    master at decision time, and the Policy gate never receives this list — so
    a neighbour that happened to be auto-closed cannot pull a sensitive case
    into automation.
    """
    from app.rag.retrieval import retrieve_similar

    excluded = exclude_ids or set()
    result = retrieve_similar(session, text, k=k + len(excluded))
    return [
        {
            "category_id": case.category_id,
            "similarity": case.similarity,
            "complaint_text": case.complaint_text,
        }
        for case in result.cases
        if case.grievance_id not in excluded
    ][:k]


def category_catalogue(session: Session) -> list[dict[str, Any]]:
    """The categories the model may choose from, straight from the master."""
    return [
        {
            "category_id": row.category_id,
            "category": row.category,
            "subcategory": row.subcategory,
            "default_priority": row.default_priority,
        }
        for row in list_categories(session)
    ]


def run_intake(
    session: Session, state: PipelineState, *, provider: LLMProvider | None = None
) -> PipelineState:
    """Produce the structured draft."""
    llm = provider or get_provider()
    catalogue = category_catalogue(session)
    neighbours = neighbour_evidence(session, state.get("raw_text", ""))

    with span(
        INTAKE_SPAN,
        language=state.get("language", "en"),
        characters=len(state.get("raw_text", "")),
        categories_offered=len(catalogue),
        neighbours_considered=len(neighbours),
    ) as current:
        completion = llm.complete_json(
            system=SYSTEM_PROMPT,
            user=state.get("raw_text", ""),
            schema_hint=SCHEMA_HINT,
            context={"categories": catalogue, "neighbours": neighbours},
        )
        draft = completion.as_json()

        location = draft.get("location") or {}
        if isinstance(location, dict):
            draft.setdefault("taluka", location.get("taluka"))
            draft.setdefault("locality", location.get("locality"))

        # Deterministic backstop: if the model did not pick up a place the
        # citizen named, match it against the talukas and localities present
        # in the loaded data. Routing should not depend on the model noticing.
        if not draft.get("taluka") or not draft.get("locality"):
            from app.services.geo import locate

            # Search the model's English restatement as well as the original:
            # a Marathi complaint may name the place in Devanagari, which the
            # Latin-script data will not match, while the restatement will.
            found = locate(
                session,
                f"{state.get('raw_text', '')} {draft.get('description') or ''}",
            )
            draft["taluka"] = draft.get("taluka") or found["taluka"]
            draft["locality"] = draft.get("locality") or found["locality"]

        # An explicit location from the caller wins over an inferred one.
        if state.get("taluka"):
            draft["taluka"] = state["taluka"]
        if state.get("locality"):
            draft["locality"] = state["locality"]

        missing = list(draft.get("missing_details") or [])
        if not draft.get("category_id"):
            missing.append("category could not be determined from the complaint")
        if not draft.get("taluka"):
            missing.append("taluka is needed to route the complaint")

        confidence = float(draft.get("confidence") or completion.confidence or 0.0)

        record(
            current,
            category_id=draft.get("category_id"),
            confidence=confidence,
            missing_details=missing,
            model=completion.model,
        )

    state["draft"] = draft
    state["intake_neighbours"] = neighbours
    state["missing_details"] = missing
    state["intake_confidence"] = confidence
    state["model"] = completion.model
    return state
