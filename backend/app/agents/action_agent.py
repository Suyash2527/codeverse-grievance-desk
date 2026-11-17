"""Action Agent.

Applies the decision: updates the case, fires the department webhook, and
records simulated email and WhatsApp updates for the citizen.

Every write goes through the guard layer. If the gate said AUTO_RESOLVE but
the category is sensitive, the guard refuses and this node records the refusal
and queues the case for a human instead of failing the run. That belt-and-
braces arrangement is deliberate: the gate already prevents it, and the guard
prevents it again at the write.

No message is ever delivered to a real address. Webhook dispatch posts to n8n
when N8N_WEBHOOK_BASE is configured, and otherwise records a mock dispatch.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.config import settings
from app.models import Grievance, Notification
from app.observability.trace import ACTION_SPAN, record, span
from app.policy.guards import (
    Actor,
    Audience,
    Destination,
    GateOutcome,
    PolicyViolation,
    assert_mock_destination,
    build_refusal_audit_entry,
    mask_identity,
)
from app.policy.store import get_department, get_policy
from app.services.grievance_service import record_audit, serialize_grievance, update_status

AUTO_RESOLVE_STATUS = "Resolved"
HUMAN_QUEUE_STATUS = "In Progress"


def _dispatch_webhook(payload: dict[str, Any], *, webhook_id: str) -> dict[str, Any]:
    """Post to n8n when configured, otherwise record a mock dispatch.

    The mock path is not a failure mode: the dataset's webhook IDs are
    placeholders, so a recorded dispatch is the correct demo behaviour.
    """
    if not settings.n8n_webhook_base:
        return {
            "delivered": False,
            "note": f"mock dispatch recorded for {webhook_id}; N8N_WEBHOOK_BASE is not set",
        }
    try:
        import httpx

        url = f"{settings.n8n_webhook_base.rstrip('/')}/{webhook_id}"
        response = httpx.post(url, json=payload, timeout=5.0)
        return {"delivered": response.is_success, "note": f"n8n responded {response.status_code}"}
    except Exception as exc:  # pragma: no cover - network failure path
        return {"delivered": False, "note": f"n8n dispatch failed, mock recorded: {exc}"}


def run_action(session: Session, state: PipelineState) -> PipelineState:
    gate = state.get("gate") or {}
    decision = state.get("decision") or {}
    grievance_ref = state.get("grievance_ref")
    actions: list[dict[str, Any]] = []

    grievance = (
        session.query(Grievance).filter_by(reference_no=grievance_ref).one_or_none()
        if grievance_ref
        else None
    )

    with span(ACTION_SPAN, grievance_ref=grievance_ref, gate_outcome=gate.get("outcome")) as current:
        if grievance is None:
            record(current, skipped="no grievance to act on")
            state["actions"] = actions
            return state

        policy = get_policy(session, grievance.category_id)
        auto = gate.get("outcome") == GateOutcome.AUTO_RESOLVE.value
        target_status = AUTO_RESOLVE_STATUS if auto else HUMAN_QUEUE_STATUS

        # 1. Status update, guarded.
        try:
            update_status(
                session,
                grievance=grievance,
                new_status=target_status,
                actor=Actor.AI_SYSTEM,
                model=state.get("model", "unknown"),
                confidence=float(gate.get("confidence") or 0.0),
                reasoning=decision.get("rationale", "pipeline decision"),
            )
            actions.append({"action": "UPDATE_STATUS", "status": target_status, "ok": True})
        except PolicyViolation as exc:
            record_audit(
                session,
                build_refusal_audit_entry(
                    actor=Actor.AI_SYSTEM,
                    attempted_action=f"UPDATE_STATUS_TO_{target_status.upper()}",
                    target=grievance.reference_no,
                    violation=exc,
                    model=state.get("model"),
                    confidence=float(gate.get("confidence") or 0.0),
                ),
            )
            # The case stays where a human can see it.
            grievance.status = HUMAN_QUEUE_STATUS
            session.flush()
            actions.append(
                {
                    "action": "UPDATE_STATUS",
                    "status": target_status,
                    "ok": False,
                    "refused_rule": exc.rule,
                    "detail": str(exc),
                }
            )
            state.setdefault("errors", []).append(str(exc))

        # 2. Department webhook, with the identity-masked payload.
        department = get_department(session, grievance.department_id or "")
        department_payload = serialize_grievance(
            session, grievance, audience=Audience.WEBHOOK
        )
        if department is None:
            actions.append(
                {
                    "action": "WEBHOOK",
                    "ok": False,
                    "detail": f"department {grievance.department_id} not in the directory",
                }
            )
        else:
            try:
                assert_mock_destination(
                    Destination(
                        channel="webhook",
                        address=department.mock_webhook_id,
                        is_real_contact=department.is_real_contact,
                        department_id=department.department_id,
                    )
                )
                result = _dispatch_webhook(
                    department_payload, webhook_id=department.mock_webhook_id
                )
                session.add(
                    Notification(
                        grievance_id=grievance.id,
                        channel="webhook",
                        destination=department.mock_webhook_id,
                        mock_webhook_id=department.mock_webhook_id,
                        payload=department_payload,
                        identity_masked=bool(department_payload.get("identity_masked")),
                        delivered=result["delivered"],
                        delivery_note=result["note"],
                    )
                )
                actions.append(
                    {
                        "action": "WEBHOOK",
                        "ok": True,
                        "destination": department.mock_webhook_id,
                        "identity_masked": bool(department_payload.get("identity_masked")),
                        "delivered": result["delivered"],
                        "note": result["note"],
                    }
                )
            except PolicyViolation as exc:
                actions.append(
                    {"action": "WEBHOOK", "ok": False, "refused_rule": exc.rule, "detail": str(exc)}
                )

        # 3. Simulated citizen updates. The citizen may see their own details,
        #    but the stored payload is masked whenever policy requires it.
        citizen_payload = mask_identity(
            {
                "reference_no": grievance.reference_no,
                "status": grievance.status,
                "department_id": grievance.department_id,
                "sla_due_at": grievance.sla_due_at.isoformat(),
                "message": (
                    f"Your grievance {grievance.reference_no} is now "
                    f"{grievance.status}. This is a demo notification."
                ),
            },
            policy=policy,
            audience=Audience.NOTIFICATION,
        )
        for channel in ("email", "whatsapp"):
            session.add(
                Notification(
                    grievance_id=grievance.id,
                    channel=channel,
                    destination=f"simulated-{channel}-recipient",
                    payload=citizen_payload,
                    identity_masked=bool(citizen_payload.get("identity_masked")),
                    delivered=False,
                    delivery_note="simulated only; no message leaves this system",
                )
            )
            actions.append({"action": "NOTIFY", "channel": channel, "ok": True, "simulated": True})

        session.flush()
        record(current, actions=actions, final_status=grievance.status)

    state["actions"] = actions
    return state
