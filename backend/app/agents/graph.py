"""The LangGraph pipeline.

    Intake -> Retrieval -> Policy -> Decision -> Action

A linear graph, deliberately. Branching on the gate outcome inside the graph
would create a second place where "is this auto-resolvable" is decided; one
answer, computed by the Policy node and enforced again at the write, is easier
to audit and harder to get wrong.

The nodes need a database session, which is bound in at build time rather than
carried through the state, so nothing serialisable ever holds a live session.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.action_agent import run_action
from app.agents.decision_agent import run_decision
from app.agents.intake import run_intake
from app.agents.policy_agent import run_policy
from app.agents.retrieval_agent import run_retrieval
from app.agents.state import PipelineState
from app.agents.summary_agent import run_summary
from app.llm.provider import LLMProvider
from app.observability.trace import current_trace_url, flush, trace_run
from app.policy.store import UnknownCategoryError
from app.services.grievance_service import create_grievance

INTAKE = "intake"
CONFIRM = "confirm"
RETRIEVAL = "retrieval"
SUMMARY = "summary"
POLICY = "policy"
DECISION = "decision"
ACTION = "action"


def build_graph(
    session: Session,
    *,
    provider: LLMProvider | None = None,
    start_at_confirm: bool = False,
):
    """Compile the pipeline with a session bound to every node.

    Ticket creation is its own node between Intake and Retrieval, so the
    ordering constraint (a ticket is created from a structured draft, never
    from raw text) is expressed in the graph rather than in a caller.
    """
    graph = StateGraph(PipelineState)

    graph.add_node(INTAKE, lambda state: run_intake(session, state, provider=provider))
    graph.add_node(CONFIRM, lambda state: _ensure_grievance(session, state))
    graph.add_node(RETRIEVAL, lambda state: run_retrieval(session, state))
    graph.add_node(SUMMARY, lambda state: run_summary(session, state, provider=provider))
    graph.add_node(POLICY, lambda state: run_policy(session, state))
    graph.add_node(DECISION, lambda state: run_decision(session, state))
    graph.add_node(ACTION, lambda state: run_action(session, state))

    # The citizen chat has already produced and shown a draft, so confirming
    # it must file exactly that draft rather than re-reading the raw text and
    # possibly filing something the citizen never saw.
    graph.add_edge(START, CONFIRM if start_at_confirm else INTAKE)
    graph.add_edge(INTAKE, CONFIRM)
    graph.add_edge(CONFIRM, RETRIEVAL)
    graph.add_edge(RETRIEVAL, SUMMARY)
    graph.add_edge(SUMMARY, POLICY)
    graph.add_edge(POLICY, DECISION)
    graph.add_edge(DECISION, ACTION)
    graph.add_edge(ACTION, END)

    return graph.compile()


def _ensure_grievance(session: Session, state: PipelineState) -> PipelineState:
    """Create the ticket from the confirmed draft, if one does not exist yet.

    The citizen chat confirms the draft before this point; the seed scripts
    and the single-shot pipeline endpoint confirm implicitly. Either way the
    ticket is created from the draft, not from the raw text.
    """
    if state.get("grievance_ref"):
        return state
    draft = state.get("draft") or {}
    category_id = draft.get("category_id")
    if not category_id:
        # Without a category there is no policy, so no ticket is created and
        # the run ends in the human queue with its reason recorded.
        return state
    try:
        grievance = create_grievance(
            session,
            complaint_text=state.get("raw_text", ""),
            category_id=category_id,
            taluka=draft.get("taluka"),
            locality=draft.get("locality"),
            language=state.get("language", "en"),
            normalised_text_en=draft.get("description"),
            citizen_name=state.get("citizen_name"),
            citizen_phone=state.get("citizen_phone"),
            citizen_email=state.get("citizen_email"),
        )
    except UnknownCategoryError:
        return state
    session.flush()
    state["grievance_ref"] = grievance.reference_no
    return state


def run_pipeline(
    session: Session,
    *,
    raw_text: str,
    language: str = "en",
    taluka: str | None = None,
    locality: str | None = None,
    citizen_name: str | None = None,
    citizen_phone: str | None = None,
    citizen_email: str | None = None,
    grievance_ref: str | None = None,
    provider: LLMProvider | None = None,
) -> dict[str, Any]:
    """Run one grievance end to end and return the full state.

    One Langfuse trace per run, with a span per agent, marked public so the
    link can be shared with a judge.
    """
    state: PipelineState = {
        "raw_text": raw_text,
        "language": language,
        "taluka": taluka,
        "locality": locality,
        "citizen_name": citizen_name,
        "citizen_phone": citizen_phone,
        "citizen_email": citizen_email,
        "grievance_ref": grievance_ref,
        "errors": [],
    }

    with trace_run(
        "grievance.pipeline",
        language=language,
        taluka=taluka,
        started_at=datetime.now(timezone.utc).isoformat(),
    ):
        compiled = build_graph(session, provider=provider)
        state = dict(compiled.invoke(state))
        state["trace_url"] = current_trace_url() or state.get("trace_url")

    session.commit()
    flush()
    return dict(state)


def run_pipeline_from_draft(
    session: Session,
    *,
    draft: dict[str, Any],
    raw_text: str,
    language: str = "en",
    citizen_name: str | None = None,
    citizen_phone: str | None = None,
    citizen_email: str | None = None,
    provider: LLMProvider | None = None,
) -> dict[str, Any]:
    """Run the pipeline from a draft the citizen has already confirmed.

    Intake is skipped because it has already happened in the chat; the graph
    starts at ticket creation so the filed case matches what was shown.
    """
    state: PipelineState = {
        "raw_text": raw_text,
        "language": language,
        "draft": draft,
        "taluka": draft.get("taluka"),
        "locality": draft.get("locality"),
        "intake_confidence": float(draft.get("confidence") or 0.0),
        "model": draft.get("model") or "citizen-confirmed-draft",
        "citizen_name": citizen_name,
        "citizen_phone": citizen_phone,
        "citizen_email": citizen_email,
        "errors": [],
    }

    with trace_run(
        "grievance.pipeline.confirmed",
        language=language,
        started_at=datetime.now(timezone.utc).isoformat(),
    ):
        compiled = build_graph(session, provider=provider, start_at_confirm=True)
        state = dict(compiled.invoke(state))
        state["trace_url"] = current_trace_url() or state.get("trace_url")

    session.commit()
    flush()
    return dict(state)


def run_pipeline_graph(
    session: Session, state: PipelineState, *, provider: LLMProvider | None = None
) -> dict[str, Any]:
    """Invoke the compiled LangGraph directly.

    Used by the graph test to prove the wiring, and available for callers that
    already have a ticket and want the nodes driven by the graph itself.
    """
    compiled = build_graph(session, provider=provider)
    return dict(compiled.invoke(state))
