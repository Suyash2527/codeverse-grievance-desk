"""Officer-facing API.

Everything here is department-facing, so every grievance payload goes through
the same masking serializer: an officer working an Identity-Hiding category
sees the case, not the complainant.

Approve and override are deliberately separate actions. Approving records that
a human agreed with the AI recommendation; overriding records that a human
disagreed and what they did instead. Both are logged under the officer's own
ID, never as AI_SYSTEM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CitizenContact, Decision, Grievance, Incident, SlaAlert
from app.policy.guards import (
    Actor,
    Audience,
    PolicyViolation,
    build_audit_entry,
    mask_identity,
)
from app.policy.store import get_category, get_policy
from app.services.grievance_service import record_audit, update_status

router = APIRouter(prefix="/api/officer", tags=["officer"])

RESOLVED_STATUS = "Resolved"


class ApproveIn(BaseModel):
    officer_id: str = Field(min_length=1)
    note: str = Field(min_length=1)
    status: str = RESOLVED_STATUS


class OverrideIn(BaseModel):
    officer_id: str = Field(min_length=1)
    note: str = Field(min_length=1)
    status: str | None = None
    department_id: str | None = None
    assignee: str | None = None
    priority: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None


def _latest_decision(session: Session, grievance: Grievance) -> Decision | None:
    return session.scalar(
        select(Decision)
        .where(Decision.grievance_id == grievance.id)
        .order_by(Decision.id.desc())
    )


def _queue_row(session: Session, grievance: Grievance, *, now: datetime) -> dict[str, Any]:
    """One queue row: the case, its policy, and the labelled AI output."""
    policy = get_policy(session, grievance.category_id)
    category_row = get_category(session, grievance.category_id)
    decision = _latest_decision(session, grievance)
    # Loaded, then masked. On a non-hiding category the officer sees the
    # complainant; on a hiding one the same code path withholds them, so the
    # contrast is produced by the policy flag rather than by two code paths.
    contact = (
        session.get(CitizenContact, grievance.citizen_contact_id)
        if grievance.citizen_contact_id
        else None
    )
    alerts = list(
        session.scalars(select(SlaAlert).where(SlaAlert.grievance_id == grievance.id))
    )
    incident = (
        session.get(Incident, grievance.incident_id) if grievance.incident_id else None
    )

    due = grievance.sla_due_at
    if due is not None and due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    hours_remaining = (due - now).total_seconds() / 3600 if due else None

    payload = {
        "reference_no": grievance.reference_no,
        "complaint_text": grievance.complaint_text,
        "complaint_language": grievance.complaint_language,
        "category_id": grievance.category_id,
        # Category and subcategory names are facts from the master. The UI
        # headlines a case with these rather than with the AI summary, which
        # would read as verified fact at headline size.
        "category": category_row.category if category_row else None,
        "subcategory": category_row.subcategory if category_row else None,
        "department_id": grievance.department_id,
        "assignee": grievance.assignee,
        "status": grievance.status,
        "priority": grievance.priority,
        "priority_score": grievance.priority_score,
        "taluka": grievance.taluka,
        "locality": grievance.locality,
        "citizen_name": contact.citizen_name if contact else None,
        "citizen_phone": contact.citizen_phone if contact else None,
        "sla_days": grievance.sla_days,
        "sla_due_at": due.isoformat() if due else None,
        "hours_remaining": round(hours_remaining, 1) if hours_remaining is not None else None,
        "overdue": bool(hours_remaining is not None and hours_remaining < 0),
        "reopened_count": grievance.reopened_count,
        "created_at": grievance.created_at.isoformat() if grievance.created_at else None,
        # Already wrapped with their AI-generated label when stored.
        "ai_summary": grievance.ai_summary,
        "ai_sentiment": grievance.ai_sentiment,
        "policy": {
            "sensitive": policy.sensitive,
            "identity_hiding": policy.identity_hiding,
            "auto_resolution_allowed": policy.auto_resolution_allowed,
            "policy_note": policy.policy_note,
            "default_priority": policy.default_priority,
        },
        "gate": None
        if decision is None
        else {
            "outcome": decision.gate_outcome,
            "rule_applied": decision.policy_rule_applied,
            "reason": decision.policy_reason,
            "confidence": decision.confidence,
            "confidence_threshold": decision.confidence_threshold,
            "model": decision.model,
            "trace_url": decision.trace_id,
        },
        "incident_id": grievance.incident_id,
        "incident": None
        if incident is None
        else {
            "incident_ref": incident.incident_ref,
            "similarity": incident.similarity,
            "confirmed_by": incident.confirmed_by,
            "member_count": session.scalar(
                select(func.count())
                .select_from(Grievance)
                .where(Grievance.incident_id == incident.id)
            ),
        },
        "sla_alerts": [
            {
                "risk": a.risk,
                "reason": a.reason,
                "predicted_days": a.predicted_days,
                "historical_p80_days": a.historical_p80_days,
                "sample_size": a.sample_size,
                "acknowledged_by": a.acknowledged_by,
            }
            for a in alerts
        ],
    }
    # Department audience: identity masked wherever the category requires it.
    return mask_identity(payload, policy=policy, audience=Audience.DEPARTMENT)


@router.get("/queue")
def get_queue(
    status: str | None = None,
    sensitive: bool | None = None,
    priority: str | None = None,
    department_id: str | None = None,
    awaiting_review: bool = Query(
        default=False, description="only cases the gate sent to the human queue"
    ),
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """The officer work queue.

    Ordered by priority then by SLA deadline, so the most urgent case with the
    least time left is first. Priority itself comes from severity, urgency and
    affected population, never from how many times something was reported.
    """
    now = datetime.now(timezone.utc)
    stmt = select(Grievance)
    if status:
        stmt = stmt.where(Grievance.status == status)
    if department_id:
        stmt = stmt.where(Grievance.department_id == department_id)
    if priority:
        stmt = stmt.where(Grievance.priority == priority)

    rows = [_queue_row(session, g, now=now) for g in session.scalars(stmt.limit(limit * 2))]

    if sensitive is not None:
        rows = [r for r in rows if r["policy"]["sensitive"] is sensitive]
    if awaiting_review:
        rows = [r for r in rows if (r["gate"] or {}).get("outcome") == "HUMAN_QUEUE"]

    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows.sort(
        key=lambda r: (
            order.get(r["priority"], 9),
            r["hours_remaining"] if r["hours_remaining"] is not None else 1e9,
        )
    )
    rows = rows[:limit]

    return {
        "generated_at": now.isoformat(),
        "count": len(rows),
        "counts": {
            "awaiting_review": sum(
                1 for r in rows if (r["gate"] or {}).get("outcome") == "HUMAN_QUEUE"
            ),
            "sensitive": sum(1 for r in rows if r["policy"]["sensitive"]),
            "overdue": sum(1 for r in rows if r["overdue"]),
        },
        "rows": rows,
    }


@router.get("/grievances/{reference_no}")
def get_case(reference_no: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")
    return _queue_row(session, grievance, now=datetime.now(timezone.utc))


@router.post("/grievances/{reference_no}/approve")
def approve(
    reference_no: str, body: ApproveIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Record that an officer agreed with the AI recommendation.

    The officer is the actor, so this is permitted on sensitive categories
    where the AI itself is refused: the point of human review is that a human
    can do what the automation may not.
    """
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")

    decision = _latest_decision(session, grievance)
    try:
        update_status(
            session,
            grievance=grievance,
            new_status=body.status,
            actor=Actor.OFFICER,
            actor_id=body.officer_id,
            reasoning=(
                f"Officer approved the AI recommendation "
                f"({(decision.policy_rule_applied if decision else 'no recorded decision')}): "
                f"{body.note}"
            ),
        )
    except PolicyViolation as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": str(exc), "rule": exc.rule}
        ) from exc
    session.commit()
    return _queue_row(session, grievance, now=datetime.now(timezone.utc))


@router.post("/grievances/{reference_no}/override")
def override(
    reference_no: str, body: OverrideIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Record that an officer disagreed with the AI and what they changed.

    Every field changed is written to the audit log under the officer ID, so
    an override is as traceable as an automated action.
    """
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")

    changes: list[str] = []
    if body.department_id and body.department_id != grievance.department_id:
        changes.append(f"department {grievance.department_id} -> {body.department_id}")
        grievance.department_id = body.department_id
    if body.assignee and body.assignee != grievance.assignee:
        changes.append(f"assignee {grievance.assignee!r} -> {body.assignee!r}")
        grievance.assignee = body.assignee
    if body.priority and body.priority != grievance.priority:
        changes.append(f"priority {grievance.priority} -> {body.priority}")
        grievance.priority = body.priority

    if changes:
        session.flush()
        record_audit(
            session,
            build_audit_entry(
                actor=Actor.OFFICER,
                actor_id=body.officer_id,
                action="OVERRIDE_AI_DECISION",
                target=grievance.reference_no,
                reasoning=f"Officer override ({'; '.join(changes)}): {body.note}",
                rule_applied="HUMAN_OVERRIDE",
            ),
        )

    if body.status:
        try:
            update_status(
                session,
                grievance=grievance,
                new_status=body.status,
                actor=Actor.OFFICER,
                actor_id=body.officer_id,
                reasoning=f"Officer override: {body.note}",
            )
        except PolicyViolation as exc:
            session.rollback()
            raise HTTPException(
                status_code=409, detail={"error": str(exc), "rule": exc.rule}
            ) from exc

    if not changes and not body.status:
        raise HTTPException(
            status_code=422, detail="an override must change at least one field"
        )

    session.commit()
    return _queue_row(session, grievance, now=datetime.now(timezone.utc))
