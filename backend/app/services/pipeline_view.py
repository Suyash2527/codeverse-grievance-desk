"""Reconstruct one pipeline run from what was actually recorded.

The problem statement asks for visible agent hand-offs. Langfuse provides
that, but only once its keys are configured and only on a reachable network —
neither is guaranteed in a demo room. This rebuilds the same picture from the
decision, the audit log and the notifications the run already wrote.

Nothing is stored for this view and nothing is inferred beyond what those
records state. A stage the run did not reach is reported as "not reached"
rather than drawn as if it succeeded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Decision, Grievance, Notification
from app.observability.trace import (
    ACTION_SPAN,
    DECISION_SPAN,
    INTAKE_SPAN,
    POLICY_SPAN,
    RETRIEVAL_SPAN,
)
from app.policy.store import get_policy

SUMMARY_SPAN = "summary.generate"


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def pipeline_view(session: Session, reference_no: str) -> dict[str, Any]:
    """The five agent hand-offs for one grievance, in order."""
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise LookupError(f"unknown reference {reference_no}")

    decision = session.scalar(
        select(Decision)
        .where(Decision.grievance_id == grievance.id)
        .order_by(Decision.id.desc())
    )
    audits = list(
        session.scalars(
            select(AuditLog)
            .where(AuditLog.target == reference_no)
            .order_by(AuditLog.id)
        )
    )
    notifications = list(
        session.scalars(
            select(Notification).where(Notification.grievance_id == grievance.id)
        )
    )
    policy = get_policy(session, grievance.category_id)

    created = _aware(grievance.created_at)
    decided = _aware(decision.created_at) if decision else None
    acted = next(
        (_aware(a.timestamp) for a in audits if a.action.startswith("UPDATE_STATUS")),
        None,
    )
    refused = [a for a in audits if a.action.startswith("REFUSED_")]

    spans: list[dict[str, Any]] = [
        {
            "name": INTAKE_SPAN,
            "agent": "Intake",
            "state": "done",
            "at": created.isoformat() if created else None,
            "summary": (
                f"Structured the complaint and proposed {grievance.category_id}."
            ),
            "detail": {
                "language": grievance.complaint_language,
                "category_id": grievance.category_id,
                "taluka": grievance.taluka,
                "model": decision.model if decision else None,
            },
        },
        {
            "name": RETRIEVAL_SPAN,
            "agent": "Retrieval",
            "state": "done" if decision else "not reached",
            "at": created.isoformat() if created else None,
            "summary": (
                f"Retrieved {len(decision.retrieved_case_ids)} similar past case(s) "
                f"as evidence."
                if decision
                else "No retrieval was recorded."
            ),
            "detail": {
                "retrieved_case_ids": decision.retrieved_case_ids if decision else [],
                "note": "Evidence only. The gate never receives these cases.",
            },
        },
        {
            "name": SUMMARY_SPAN,
            "agent": "Summary",
            "state": "done" if grievance.ai_summary else "not reached",
            "at": created.isoformat() if created else None,
            "summary": (
                (grievance.ai_summary or {}).get("value")
                or "No summary was generated."
            ),
            "detail": {
                "labelled": bool(grievance.ai_summary),
                "sentiment": (grievance.ai_sentiment or {}).get("value"),
            },
        },
        {
            "name": POLICY_SPAN,
            "agent": "Policy",
            "state": "done" if decision else "not reached",
            "at": decided.isoformat() if decided else None,
            "summary": (
                decision.policy_reason if decision else "No gate decision recorded."
            ),
            "detail": {
                "outcome": decision.gate_outcome if decision else None,
                "rule_applied": decision.policy_rule_applied if decision else None,
                "confidence": decision.confidence if decision else None,
                "threshold": decision.confidence_threshold if decision else None,
                "sensitive": policy.sensitive,
                "identity_hiding": policy.identity_hiding,
            },
        },
        {
            "name": DECISION_SPAN,
            "agent": "Decision",
            "state": "done" if decision else "not reached",
            "at": decided.isoformat() if decided else None,
            "summary": (
                f"Routed to {grievance.department_id} at priority "
                f"{grievance.priority}."
            ),
            "detail": {
                "department_id": grievance.department_id,
                "assignee": grievance.assignee,
                "priority": grievance.priority,
                "priority_score": grievance.priority_score,
                "sla_days": grievance.sla_days,
            },
        },
        {
            "name": ACTION_SPAN,
            "agent": "Action",
            "state": "refused" if refused else ("done" if acted else "not reached"),
            "at": acted.isoformat() if acted else None,
            "summary": (
                f"Refused: {refused[0].rule_applied}"
                if refused
                else f"Status set to {grievance.status}; "
                f"{len(notifications)} dispatch(es) recorded."
            ),
            "detail": {
                "status": grievance.status,
                "refusals": [
                    {"action": a.action, "rule": a.rule_applied, "reason": a.reasoning}
                    for a in refused
                ],
                "dispatches": [
                    {
                        "channel": n.channel,
                        "destination": n.destination,
                        "identity_masked": n.identity_masked,
                        "delivered": n.delivered,
                        "note": n.delivery_note,
                    }
                    for n in notifications
                ],
            },
        },
    ]

    elapsed_ms = None
    if created and acted:
        elapsed_ms = round((acted - created).total_seconds() * 1000)

    return {
        "reference_no": reference_no,
        "spans": spans,
        "elapsed_ms": elapsed_ms,
        "trace_url": decision.trace_id if decision else None,
        "note": (
            "Reconstructed from the decision record, audit log and dispatch log "
            "written by the run itself. Nothing here is inferred."
        ),
    }
