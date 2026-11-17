"""FastAPI application: M1 surface.

Milestone 1 ships the data-backed read endpoints, grievance creation, and the
guarded status-update endpoint that hard rule 1 depends on. The agent
pipeline, duplicates, SLA job and citizen chat arrive in later milestones.

Every policy violation is returned as HTTP 409 with the violated rule named,
so a judge can see the refusal rather than a generic error.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session, init_db
from app.loaders import reload_reference_data
from app.models import AuditLog, Decision, Grievance, GrievanceHistory
from app.policy.guards import (
    Actor,
    Audience,
    PolicyViolation,
    build_refusal_audit_entry,
    label_ai_output,
)
from app.policy.store import (
    UnknownCategoryError,
    get_policy,
    list_categories,
    list_departments,
)
from app.services.grievance_service import (
    create_grievance,
    record_audit,
    reopen_on_dispute,
    serialize_grievance,
    update_status,
)

app = FastAPI(
    title="HackFusion Agentic Grievance Redressal API",
    version="0.1.0",
    description=(
        "Mock backend for the HackFusion 4.0 grievance-redressal prototype. "
        "All category, SLA, department, taluka and contact values are loaded "
        "from CSV at runtime. All contact details in the dataset are "
        "non-operational placeholders and nothing is ever delivered to a real "
        "address."
    ),
)

from app.api.citizen import router as citizen_router  # noqa: E402
from app.api.compliance import router as compliance_router  # noqa: E402
from app.api.officer import router as officer_router  # noqa: E402
from app.api.operations import router as operations_router  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(citizen_router)
app.include_router(compliance_router)
app.include_router(officer_router)
app.include_router(operations_router)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class CategoryOut(BaseModel):
    category_id: str
    category: str
    subcategory: str
    responsible_department_id: str
    responsible_department: str
    default_assignee: str
    sla_days: int
    sensitive: bool
    identity_hiding: bool
    default_priority: str
    auto_resolution_allowed: bool
    policy_note: str


class DepartmentOut(BaseModel):
    department_id: str
    department_name: str
    service_scope: str
    jurisdiction_type: str
    jurisdiction_talukas: list[str]
    contact_email_demo: str
    contact_channel: str
    mock_webhook_id: str
    is_real_contact: bool


class GrievanceCreate(BaseModel):
    complaint_text: str = Field(min_length=1)
    category_id: str
    taluka: str | None = None
    locality: str | None = None
    language: str = "en"
    citizen_name: str | None = None
    citizen_phone: str | None = None
    citizen_email: str | None = None


class StatusUpdate(BaseModel):
    status: str
    actor: Literal["AI_SYSTEM", "OFFICER"]
    actor_id: str | None = None
    model: str | None = None
    confidence: float | None = None
    reasoning: str = Field(min_length=1)


class DisputeIn(BaseModel):
    note: str = Field(min_length=1)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _get_grievance(session: Session, reference_no: str) -> Grievance:
    row = session.scalar(select(Grievance).where(Grievance.reference_no == reference_no))
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")
    return row


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@app.get("/api/health")
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    return {
        "status": "ok",
        "data_dir": str(settings.data_dir),
        "categories_loaded": len(list_categories(session)),
        "departments_loaded": len(list_departments(session)),
        "confidence_threshold": settings.confidence_threshold,
    }


@app.post("/api/admin/reload-reference-data")
def reload_data(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Re-read the CSVs in DATA_DIR and replace the configuration tables.

    This is how a replacement category CSV takes effect without a code change
    or a restart.
    """
    return reload_reference_data(session).as_dict()


@app.get("/api/categories", response_model=list[CategoryOut])
def get_categories(session: Session = Depends(get_session)) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c, from_attributes=True) for c in list_categories(session)]


@app.get("/api/departments", response_model=list[DepartmentOut])
def get_departments(session: Session = Depends(get_session)) -> list[DepartmentOut]:
    return [
        DepartmentOut.model_validate(d, from_attributes=True)
        for d in list_departments(session)
    ]


@app.get("/api/grievances/history")
def search_history(
    q: str | None = Query(default=None, description="substring of complaint text"),
    category_id: str | None = None,
    department_id: str | None = None,
    taluka: str | None = None,
    status: str | None = None,
    limit: int = Query(default=25, le=200),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    """Keyword search over historical cases.

    Semantic retrieval arrives with the RAG milestone; this is the plain
    filter used for inspection and for the officer-facing evidence panel
    fallback when embeddings are unavailable.
    """
    stmt = select(GrievanceHistory)
    if q:
        stmt = stmt.where(GrievanceHistory.complaint_text.ilike(f"%{q}%"))
    if category_id:
        stmt = stmt.where(GrievanceHistory.category_id == category_id)
    if department_id:
        stmt = stmt.where(GrievanceHistory.department_id == department_id)
    if taluka:
        stmt = stmt.where(GrievanceHistory.broad_location_taluka == taluka)
    if status:
        stmt = stmt.where(GrievanceHistory.status == status)
    rows = session.scalars(stmt.limit(limit))
    return [
        {
            "grievance_id": r.grievance_id,
            "complaint_text": r.complaint_text,
            "category_id": r.category_id,
            "subcategory": r.subcategory,
            "department_id": r.department_id,
            "taluka": r.broad_location_taluka,
            "locality": r.broad_location_locality,
            "submission_date": r.submission_date,
            "resolution_date": r.resolution_date,
            "resolution_days": r.resolution_days,
            "status": r.status,
            "citizen_feedback": r.citizen_feedback,
            "sla_days": r.sla_days,
            "resolution_actor": r.resolution_actor,
            "ai_auto_closed": r.ai_auto_closed,
            "data_origin": r.data_origin,
        }
        for r in rows
    ]


@app.post("/api/grievances", status_code=201)
def post_grievance(
    body: GrievanceCreate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        grievance = create_grievance(
            session,
            complaint_text=body.complaint_text,
            category_id=body.category_id,
            taluka=body.taluka,
            locality=body.locality,
            language=body.language,
            citizen_name=body.citizen_name,
            citizen_phone=body.citizen_phone,
            citizen_email=body.citizen_email,
        )
    except UnknownCategoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()
    return serialize_grievance(session, grievance, audience=Audience.CITIZEN_SELF)


@app.get("/api/grievances/{reference_no}")
def get_grievance(
    reference_no: str,
    audience: Literal["CITIZEN_SELF", "DEPARTMENT"] = "CITIZEN_SELF",
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    grievance = _get_grievance(session, reference_no)
    return serialize_grievance(session, grievance, audience=Audience(audience))


@app.patch("/api/grievances/{reference_no}/status")
def patch_status(
    reference_no: str, body: StatusUpdate, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Update a status, refusing anything the policy guards disallow.

    A request from AI_SYSTEM to close a Sensitive case is rejected here even
    if the agent asked for it, and the refusal names the rule.
    """
    grievance = _get_grievance(session, reference_no)
    try:
        update_status(
            session,
            grievance=grievance,
            new_status=body.status,
            actor=Actor(body.actor),
            actor_id=body.actor_id,
            model=body.model,
            confidence=body.confidence,
            reasoning=body.reasoning,
        )
    except PolicyViolation as exc:
        # Discard the attempted change, then record the refusal itself: a
        # blocked AI action belongs in the audit trail (rule 4).
        session.rollback()
        record_audit(
            session,
            build_refusal_audit_entry(
                actor=Actor(body.actor),
                attempted_action=f"UPDATE_STATUS_TO_{body.status.upper()}",
                target=reference_no,
                violation=exc,
                actor_id=body.actor_id,
                model=body.model,
                confidence=body.confidence,
            ),
        )
        session.commit()
        raise HTTPException(
            status_code=409,
            detail={"error": str(exc), "rule": exc.rule, "reference_no": reference_no},
        ) from exc
    session.commit()
    return serialize_grievance(session, grievance, audience=Audience.CITIZEN_SELF)


@app.post("/api/grievances/{reference_no}/dispute")
def post_dispute(
    reference_no: str, body: DisputeIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """A disputed resolution reopens the case automatically."""
    grievance = _get_grievance(session, reference_no)
    reopen_on_dispute(session, grievance=grievance, citizen_note=body.note)
    session.commit()
    return serialize_grievance(session, grievance, audience=Audience.CITIZEN_SELF)


@app.get("/api/grievances/{reference_no}/policy")
def get_grievance_policy(
    reference_no: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """The live policy currently governing a case.

    Reads the category master now, so the officer sees the policy that will
    actually be enforced rather than the one in force when the case opened.
    """
    grievance = _get_grievance(session, reference_no)
    policy = get_policy(session, grievance.category_id)
    return {
        "reference_no": grievance.reference_no,
        "category_id": policy.category_id,
        "sensitive": policy.sensitive,
        "identity_hiding": policy.identity_hiding,
        "auto_resolution_allowed": policy.auto_resolution_allowed,
        "sla_days": policy.sla_days,
        "default_priority": policy.default_priority,
        "responsible_department_id": policy.responsible_department_id,
        "default_assignee": policy.default_assignee,
        "policy_note": policy.policy_note,
        "confidence_threshold": settings.confidence_threshold,
    }


class PipelineRunIn(BaseModel):
    raw_text: str = Field(min_length=1)
    language: str = "en"
    taluka: str | None = None
    locality: str | None = None
    citizen_name: str | None = None
    citizen_phone: str | None = None
    citizen_email: str | None = None


@app.post("/api/pipeline/run")
def post_pipeline_run(
    body: PipelineRunIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Run Intake -> Retrieval -> Policy -> Decision -> Action on one complaint.

    Returns the whole state, including the policy rule that applied, the
    retrieved case ids and the Langfuse trace URL when tracing is configured.
    """
    from app.agents.graph import run_pipeline

    state = run_pipeline(
        session,
        raw_text=body.raw_text,
        language=body.language,
        taluka=body.taluka,
        locality=body.locality,
        citizen_name=body.citizen_name,
        citizen_phone=body.citizen_phone,
        citizen_email=body.citizen_email,
    )
    return {
        "grievance_ref": state.get("grievance_ref"),
        "draft": state.get("draft"),
        "missing_details": state.get("missing_details"),
        "gate": state.get("gate"),
        "decision": state.get("decision"),
        "evidence": state.get("evidence"),
        "actions": state.get("actions"),
        "errors": state.get("errors"),
        "trace_url": state.get("trace_url"),
    }


@app.get("/api/grievances/{reference_no}/explain")
def get_explanation(
    reference_no: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """The explainability panel: retrieved cases, rule applied, confidence.

    Everything the AI produced is labelled as AI-generated and unverified
    (rule 6); the policy rule and the SLA are facts read from the master.
    """
    grievance = _get_grievance(session, reference_no)
    decision = session.scalar(
        select(Decision)
        .where(Decision.grievance_id == grievance.id)
        .order_by(Decision.id.desc())
    )
    policy = get_policy(session, grievance.category_id)
    history = {
        row.grievance_id: row
        for row in session.scalars(
            select(GrievanceHistory).where(
                GrievanceHistory.grievance_id.in_(
                    decision.retrieved_case_ids if decision else []
                )
            )
        )
    }
    return {
        "reference_no": grievance.reference_no,
        "status": grievance.status,
        "policy": {
            "category_id": policy.category_id,
            "sensitive": policy.sensitive,
            "identity_hiding": policy.identity_hiding,
            "auto_resolution_allowed": policy.auto_resolution_allowed,
            "sla_days": policy.sla_days,
            "policy_note": policy.policy_note,
        },
        "decision": None
        if decision is None
        else {
            "gate_outcome": decision.gate_outcome,
            "policy_rule_applied": decision.policy_rule_applied,
            "policy_reason": decision.policy_reason,
            "confidence": decision.confidence,
            "confidence_threshold": decision.confidence_threshold,
            "model": decision.model,
            "trace_url": decision.trace_id,
            "rationale": label_ai_output(
                decision.rationale, kind="decision_rationale", model=decision.model
            ),
        },
        "retrieved_cases": [
            {
                "grievance_id": case_id,
                "complaint_text": history[case_id].complaint_text if case_id in history else None,
                "status": history[case_id].status if case_id in history else None,
                "resolution_days": history[case_id].resolution_days if case_id in history else None,
                "citizen_feedback": history[case_id].citizen_feedback if case_id in history else None,
            }
            for case_id in (decision.retrieved_case_ids if decision else [])
        ],
        "evidence_note": (
            "Retrieved cases are supporting evidence only. The outcome was "
            "decided by the category policy, not by these cases."
        ),
    }


@app.get("/api/audit-logs")
def get_audit_logs(
    target: str | None = None,
    actor: str | None = None,
    limit: int = Query(default=100, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if target:
        stmt = stmt.where(AuditLog.target == target)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    rows = session.scalars(stmt.limit(limit))
    return [
        {
            "id": r.id,
            "actor": r.actor,
            "actor_id": r.actor_id,
            "model": r.model,
            "confidence": r.confidence,
            "timestamp": r.timestamp,
            "action": r.action,
            "target": r.target,
            "reasoning": r.reasoning,
            "rule_applied": r.rule_applied,
        }
        for r in rows
    ]
