"""Scheduled jobs and incident endpoints.

The SLA scan is a plain endpoint rather than an in-process scheduler: n8n or
cron triggers it, it takes an injectable `now`, and it is therefore directly
testable and demonstrable without waiting for a real deadline to pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Grievance, SlaAlert
from app.services import duplicates, hotspots as hotspots_service, sla
from app.services.pipeline_view import pipeline_view

router = APIRouter(prefix="/api", tags=["operations"])


class ConfirmIncidentIn(BaseModel):
    officer_id: str = Field(min_length=1)
    note: str = Field(min_length=1)


def _parse_now(now: str | None) -> datetime | None:
    if not now:
        return None
    try:
        parsed = datetime.fromisoformat(now)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"now must be an ISO timestamp, got {now!r}"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.post("/jobs/sla-scan")
def run_sla_scan(
    now: str | None = Query(
        default=None,
        description="ISO timestamp to evaluate against; defaults to the current time",
    ),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Assess every open case and raise escalation alerts before deadlines."""
    return sla.scan(session, now=_parse_now(now))


@router.get("/sla/alerts")
def get_alerts(
    risk: str | None = None,
    limit: int = Query(default=100, le=500),
    session: Session = Depends(get_session),
) -> list[dict[str, Any]]:
    stmt = select(SlaAlert).order_by(SlaAlert.id.desc())
    if risk:
        stmt = stmt.where(SlaAlert.risk == risk)
    alerts = list(session.scalars(stmt.limit(limit)))
    references = {
        g.id: g.reference_no
        for g in session.scalars(
            select(Grievance).where(
                Grievance.id.in_([a.grievance_id for a in alerts] or [0])
            )
        )
    }
    return [
        {
            "id": alert.id,
            "reference_no": references.get(alert.grievance_id),
            "risk": alert.risk,
            "reason": alert.reason,
            "predicted_days": alert.predicted_days,
            "historical_p80_days": alert.historical_p80_days,
            "sample_size": alert.sample_size,
            "sla_days": alert.sla_days,
            "due_at": alert.due_at.isoformat() if alert.due_at else None,
            "raised_at": alert.raised_at.isoformat() if alert.raised_at else None,
            "acknowledged_by": alert.acknowledged_by,
        }
        for alert in alerts
    ]


@router.get("/sla/forecast/{reference_no}")
def get_forecast(
    reference_no: str,
    now: str | None = None,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """The full SLA assessment for one case, including its evidence base."""
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")
    assessment = sla.assess(
        session, grievance, now=_parse_now(now) or datetime.now(timezone.utc)
    )
    return assessment.as_dict()


@router.get("/grievances/{reference_no}/pipeline")
def get_pipeline(
    reference_no: str, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """The agent hand-offs for one case, rebuilt from what the run recorded.

    Works with or without Langfuse: when tracing is configured the Langfuse
    link is included alongside.
    """
    try:
        return pipeline_view(session, reference_no)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/analytics/hotspots")
def get_hotspots(
    now: str | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Per-taluka pressure and historical SLA failure.

    Aggregated to taluka only, with small sensitive cells suppressed, so the
    view can be shown on a shared screen without exposing a complainant.
    """
    return hotspots_service.hotspots(session, now=_parse_now(now))


@router.post("/incidents/group")
def post_group_duplicates(
    now: str | None = None, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Run duplicate detection and link groups into incidents."""
    return duplicates.group_duplicates(session, now=_parse_now(now))


@router.get("/incidents")
def get_incidents(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return duplicates.list_incidents(session)


@router.post("/incidents/{incident_id}/confirm")
def post_confirm_incident(
    incident_id: int,
    body: ConfirmIncidentIn,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    try:
        return duplicates.confirm_incident(
            session,
            incident_id=incident_id,
            officer_id=body.officer_id,
            note=body.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
