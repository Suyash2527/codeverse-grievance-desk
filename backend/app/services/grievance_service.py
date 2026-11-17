"""Write paths for grievances.

Every mutation goes through here, and every mutation calls the guard layer
before it touches the database and writes an audit entry after it does. No
endpoint, agent or script is permitted to update a status directly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuditLog, CitizenContact, Grievance
from app.policy.guards import (
    Actor,
    Audience,
    PolicySnapshot,
    authorize_status_change,
    build_audit_entry,
    mask_identity,
)
from app.policy.store import get_policy


def new_reference_no(now: datetime | None = None) -> str:
    """A human-quotable reference number, distinct from the history series."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"GRV-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def record_audit(session: Session, entry: dict[str, Any]) -> AuditLog:
    """Persist one audit entry built by the guard layer."""
    row = AuditLog(**entry)
    session.add(row)
    return row


def create_grievance(
    session: Session,
    *,
    complaint_text: str,
    category_id: str,
    taluka: str | None = None,
    locality: str | None = None,
    language: str = "en",
    normalised_text_en: str | None = None,
    actor: Actor = Actor.CITIZEN,
    actor_id: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    reasoning: str = "Grievance created from confirmed citizen draft.",
    citizen_name: str | None = None,
    citizen_phone: str | None = None,
    citizen_email: str | None = None,
    now: datetime | None = None,
) -> Grievance:
    """Create a grievance, routed and SLA-stamped from the live master.

    Department, assignee, SLA and starting priority all come from the category
    master row; none of them is hardcoded. The SLA due date is snapshotted so
    the promise shown to the citizen does not move, while the policy flags are
    deliberately not relied on later: enforcement always re-reads the master.
    """
    created = now or datetime.now(timezone.utc)
    policy = get_policy(session, category_id)

    contact_id = None
    if any([citizen_name, citizen_phone, citizen_email]):
        contact = CitizenContact(
            citizen_name=citizen_name,
            citizen_phone=citizen_phone,
            citizen_email=citizen_email,
            preferred_language=language,
        )
        session.add(contact)
        session.flush()
        contact_id = contact.id

    grievance = Grievance(
        reference_no=new_reference_no(created),
        complaint_text=complaint_text,
        complaint_language=language,
        normalised_text_en=normalised_text_en,
        category_id=policy.category_id,
        department_id=policy.responsible_department_id,
        assignee=policy.default_assignee,
        status="Submitted",
        priority=policy.default_priority,
        taluka=taluka,
        locality=locality,
        citizen_contact_id=contact_id,
        identity_masked=policy.identity_hiding,
        sla_days=policy.sla_days,
        sla_due_at=created + timedelta(days=policy.sla_days),
        created_at=created,
        updated_at=created,
    )
    session.add(grievance)
    session.flush()

    record_audit(
        session,
        build_audit_entry(
            actor=actor,
            actor_id=actor_id or ("citizen" if actor is Actor.CITIZEN else None),
            model=model,
            confidence=confidence,
            action="CREATE_GRIEVANCE",
            target=grievance.reference_no,
            reasoning=reasoning,
            rule_applied="ROUTED_FROM_CATEGORY_MASTER",
            timestamp=created,
        ),
    )
    return grievance


def update_status(
    session: Session,
    *,
    grievance: Grievance,
    new_status: str,
    actor: Actor,
    actor_id: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    reasoning: str,
    enforce_threshold: bool = True,
    now: datetime | None = None,
) -> Grievance:
    """Change a grievance status, or raise a PolicyViolation.

    The guard is given the policy read from the master right now, not the
    flags stored on this row when it was created. A category that becomes
    Sensitive after a ticket was opened immediately stops being auto-closable.
    """
    policy: PolicySnapshot = get_policy(session, grievance.category_id)
    threshold = settings.confidence_threshold if enforce_threshold else None

    rule = authorize_status_change(
        actor=actor,
        policy=policy,
        new_status=new_status,
        confidence=confidence,
        threshold=threshold,
    )

    previous = grievance.status
    grievance.status = new_status.strip()
    grievance.updated_at = now or datetime.now(timezone.utc)
    session.flush()

    record_audit(
        session,
        build_audit_entry(
            actor=actor,
            actor_id=actor_id,
            model=model,
            confidence=confidence,
            action="UPDATE_STATUS",
            target=grievance.reference_no,
            reasoning=f"{reasoning} (status {previous!r} -> {grievance.status!r})",
            rule_applied=rule,
            timestamp=grievance.updated_at,
        ),
    )
    return grievance


def reopen_on_dispute(
    session: Session,
    *,
    grievance: Grievance,
    citizen_note: str,
    now: datetime | None = None,
) -> Grievance:
    """Reopen a case because the citizen disputed its resolution.

    A dispute is a citizen action, so it is never blocked by the AI status
    allow-list; it always returns the case to a human queue.
    """
    moment = now or datetime.now(timezone.utc)
    previous = grievance.status
    grievance.status = "In Progress"
    grievance.reopened_count += 1
    grievance.updated_at = moment
    session.flush()

    record_audit(
        session,
        build_audit_entry(
            actor=Actor.CITIZEN,
            actor_id=grievance.reference_no,
            action="REOPEN_ON_DISPUTE",
            target=grievance.reference_no,
            reasoning=(
                f"Citizen disputed the resolution: {citizen_note} "
                f"(status {previous!r} -> {grievance.status!r})"
            ),
            rule_applied="CITIZEN_DISPUTE_REOPENS_CASE",
            timestamp=moment,
        ),
    )
    return grievance


def serialize_grievance(
    session: Session,
    grievance: Grievance,
    *,
    audience: Audience,
) -> dict[str, Any]:
    """Serialise a grievance for one audience, masking where policy requires.

    Department views, webhook bodies and notification payloads all come
    through this one function, so identity masking has a single test surface.
    """
    policy = get_policy(session, grievance.category_id)
    contact = (
        session.get(CitizenContact, grievance.citizen_contact_id)
        if grievance.citizen_contact_id
        else None
    )
    payload: dict[str, Any] = {
        "reference_no": grievance.reference_no,
        "complaint_text": grievance.complaint_text,
        "category_id": grievance.category_id,
        "department_id": grievance.department_id,
        "assignee": grievance.assignee,
        "status": grievance.status,
        "priority": grievance.priority,
        "taluka": grievance.taluka,
        "locality": grievance.locality,
        "sla_days": grievance.sla_days,
        # ISO strings, not datetimes: this payload is stored in a JSON column
        # and posted to webhooks, both of which need it serialisable.
        "sla_due_at": grievance.sla_due_at.isoformat() if grievance.sla_due_at else None,
        "created_at": grievance.created_at.isoformat() if grievance.created_at else None,
        "reopened_count": grievance.reopened_count,
        "citizen_name": contact.citizen_name if contact else None,
        "citizen_phone": contact.citizen_phone if contact else None,
        "citizen_email": contact.citizen_email if contact else None,
    }
    return mask_identity(payload, policy=policy, audience=audience)
