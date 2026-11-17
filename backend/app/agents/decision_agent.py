"""Decision Agent.

Turns the gate outcome into a concrete routing decision, computes priority
from the three permitted signals, and stores the decision with its evidence.

Nothing here can override the gate. If the gate said HUMAN_QUEUE, this node
assigns and queues; it never promotes a case to automation.
"""
from __future__ import annotations

import math
from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.models import Decision, Grievance
from app.observability.trace import DECISION_SPAN, current_trace_url, record, span
from app.policy.guards import (
    GateDecision,
    GateOutcome,
    PriorityInputs,
    build_decision_record,
    compute_priority,
)
from app.policy.store import get_department, get_policy

#: Population at which the affected-population signal saturates. A complaint
#: affecting a whole locality should not score ten times one affecting a
#: street, so the scale is logarithmic.
POPULATION_SATURATION = 1000


def normalise_population(estimate: Any) -> float:
    """Map a reported headcount to 0..1 on a log scale.

    This is the number of PEOPLE the citizen says are affected, never the
    number of complaints filed. Rule 7 forbids volume from driving priority,
    and PriorityInputs has no field that could carry it.
    """
    try:
        people = max(0, int(estimate or 0))
    except (TypeError, ValueError):
        return 0.0
    if people <= 0:
        return 0.0
    return min(1.0, math.log10(1 + people) / math.log10(1 + POPULATION_SATURATION))


def _as_score(value: Any, fallback: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return fallback


def run_decision(session: Session, state: PipelineState) -> PipelineState:
    draft = state.get("draft") or {}
    gate = state.get("gate") or {}
    grievance_ref = state.get("grievance_ref")

    grievance = (
        session.query(Grievance).filter_by(reference_no=grievance_ref).one_or_none()
        if grievance_ref
        else None
    )

    with span(
        DECISION_SPAN,
        gate_outcome=gate.get("outcome"),
        grievance_ref=grievance_ref,
    ) as current:
        priority, score = compute_priority(
            PriorityInputs(
                severity=_as_score(draft.get("severity")),
                urgency=_as_score(draft.get("urgency_score")),
                affected_population=normalise_population(
                    draft.get("affected_population_estimate")
                ),
            ),
            category_default=(
                get_policy(session, grievance.category_id).default_priority
                if grievance
                else None
            ),
        )

        department = None
        assignee = None
        if grievance:
            policy = get_policy(session, grievance.category_id)
            department_row = get_department(session, policy.responsible_department_id)
            department = policy.responsible_department_id
            assignee = policy.default_assignee
            grievance.priority = priority
            grievance.priority_score = score
            grievance.department_id = department
            grievance.assignee = assignee
            if department_row is None:
                state.setdefault("errors", []).append(
                    f"department {department} is not in the directory; "
                    f"routing recorded but no contact channel is available"
                )
            session.flush()

        rationale = (
            f"{gate.get('reason', 'policy gate evaluated')} "
            f"Priority {priority} (score {score:.2f}) from severity, urgency and "
            f"affected population. "
            f"{len(state.get('retrieved_case_ids') or [])} similar past case(s) "
            f"were retrieved as supporting evidence and did not determine this "
            f"outcome."
        )

        record_payload = build_decision_record(
            grievance_ref=grievance_ref or "UNSAVED_DRAFT",
            gate=GateDecision(
                outcome=GateOutcome(gate.get("outcome", GateOutcome.HUMAN_QUEUE.value)),
                rule_applied=gate.get("rule_applied", "UNSPECIFIED"),
                reason=gate.get("reason", ""),
                confidence=float(gate.get("confidence") or 0.0),
                threshold=float(gate.get("threshold") or 0.0),
                policy_note=gate.get("policy_note", ""),
            ),
            retrieved_case_ids=state.get("retrieved_case_ids") or [],
            model=state.get("model", "unknown"),
            rationale=rationale,
        )

        trace_url = current_trace_url()
        if grievance:
            session.add(
                Decision(
                    grievance_id=grievance.id,
                    gate_outcome=record_payload["gate_outcome"],
                    policy_rule_applied=record_payload["policy_rule_applied"],
                    policy_reason=record_payload["policy_reason"],
                    confidence=record_payload["confidence"],
                    confidence_threshold=record_payload["confidence_threshold"],
                    retrieved_case_ids=record_payload["retrieved_case_ids"],
                    model=record_payload["model"],
                    rationale=record_payload["rationale"],
                    trace_id=trace_url,
                )
            )
            session.flush()

        record(
            current,
            priority=priority,
            priority_score=round(score, 4),
            department_id=department,
            assignee=assignee,
            rule_applied=record_payload["policy_rule_applied"],
        )

    record_payload["priority"] = priority
    record_payload["priority_score"] = score
    record_payload["department_id"] = department
    record_payload["assignee"] = assignee
    state["decision"] = record_payload
    state["trace_url"] = trace_url
    return state
