"""SLA prediction and escalation.

Plain statistics over the historical resolution durations, not a model. The
supplied history makes a naive predictor useless: 65% of its closed cases
already exceeded their configured SLA, so "historical duration > sla_days"
would flag essentially every ticket and tell an officer nothing.

What this does instead:

* Compares the p80 historical duration for the case's own category and
  department against the SLA configured in the master.
* Reports the sample size and the basis the estimate came from, and refuses
  to give a number at all when there is too little history.
* Raises the escalation alert from the DEADLINE, not from the prediction, so
  an alert always arrives before the due time even when history is thin. The
  prediction ranks the queue; the deadline triggers the alert.

Recurrence is reported separately: a locality that keeps producing the same
category of complaint is a different problem from one slow ticket.
"""
from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Grievance, GrievanceHistory, SlaAlert
from app.policy.guards import Actor, build_audit_entry
from app.policy.store import get_policy
from app.services.grievance_service import record_audit

#: Below this many closed historical cases, no duration estimate is offered.
MIN_SAMPLES = int(os.environ.get("SLA_MIN_SAMPLES", "8"))

#: An open case is escalated when this share of its SLA window remains.
#: 0.25 of a 1-day SLA is 6 hours; of a 15-day SLA, under 4 days.
ESCALATION_REMAINING_FRACTION = float(
    os.environ.get("SLA_ESCALATION_REMAINING_FRACTION", "0.25")
)

#: How many past cases in the same category and locality count as recurring.
RECURRENCE_MIN_CASES = int(os.environ.get("SLA_RECURRENCE_MIN_CASES", "3"))

RISK_BREACH_LIKELY = "BREACH_LIKELY"
RISK_AT_RISK = "AT_RISK"
RISK_ON_TRACK = "ON_TRACK"
RISK_OVERDUE = "OVERDUE"
RISK_UNKNOWN = "INSUFFICIENT_HISTORY"

BASIS_CATEGORY_DEPARTMENT = "category+department"
BASIS_CATEGORY = "category"
BASIS_DEPARTMENT = "department"
BASIS_NONE = "no comparable history"


@dataclass(frozen=True)
class DurationStats:
    """What the history says about how long this kind of case actually takes."""

    basis: str
    sample_size: int
    p50_days: float | None
    p80_days: float | None
    breach_rate: float | None
    sla_days: int

    @property
    def usable(self) -> bool:
        return self.sample_size >= MIN_SAMPLES and self.p80_days is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"usable": self.usable, "min_samples": MIN_SAMPLES}


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * len(ordered)) - 1))
    return float(ordered[index])


def _durations(
    session: Session, *, category_id: str | None, department_id: str | None
) -> list[int]:
    stmt = select(GrievanceHistory.resolution_days).where(
        GrievanceHistory.resolution_days.isnot(None)
    )
    if category_id:
        stmt = stmt.where(GrievanceHistory.category_id == category_id)
    if department_id:
        stmt = stmt.where(GrievanceHistory.department_id == department_id)
    return [int(value) for value in session.scalars(stmt) if value is not None]


def duration_stats(
    session: Session, *, category_id: str, department_id: str | None, sla_days: int
) -> DurationStats:
    """Historical durations, falling back through progressively broader bases.

    The basis is reported so an officer can tell a department-specific
    estimate from a district-wide one.
    """
    attempts = [
        (BASIS_CATEGORY_DEPARTMENT, category_id, department_id),
        (BASIS_CATEGORY, category_id, None),
        (BASIS_DEPARTMENT, None, department_id),
    ]
    for basis, category, department in attempts:
        if basis == BASIS_CATEGORY_DEPARTMENT and not department:
            continue
        if basis == BASIS_DEPARTMENT and not department:
            continue
        values = _durations(session, category_id=category, department_id=department)
        if len(values) >= MIN_SAMPLES:
            breaches = sum(1 for value in values if value > sla_days)
            return DurationStats(
                basis=basis,
                sample_size=len(values),
                p50_days=float(statistics.median(values)),
                p80_days=_percentile(values, 0.8),
                breach_rate=round(breaches / len(values), 3),
                sla_days=sla_days,
            )

    # Nothing met the sample threshold; report the best available count
    # honestly rather than estimating from three cases.
    values = _durations(session, category_id=category_id, department_id=None)
    return DurationStats(
        basis=BASIS_NONE,
        sample_size=len(values),
        p50_days=float(statistics.median(values)) if values else None,
        p80_days=_percentile(values, 0.8) if values else None,
        breach_rate=None,
        sla_days=sla_days,
    )


def recurrence_count(
    session: Session, *, category_id: str, locality: str | None, taluka: str | None
) -> int:
    """How many past cases of this category came from the same place."""
    if not locality and not taluka:
        return 0
    stmt = select(GrievanceHistory.grievance_id).where(
        GrievanceHistory.category_id == category_id
    )
    if locality:
        stmt = stmt.where(GrievanceHistory.broad_location_locality == locality)
    elif taluka:
        stmt = stmt.where(GrievanceHistory.broad_location_taluka == taluka)
    return len(list(session.scalars(stmt)))


@dataclass
class SlaAssessment:
    reference_no: str
    risk: str
    hours_remaining: float
    due_at: datetime
    sla_days: int
    stats: DurationStats
    recurrence: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_no": self.reference_no,
            "risk": self.risk,
            "hours_remaining": round(self.hours_remaining, 1),
            "due_at": self.due_at.isoformat(),
            "sla_days": self.sla_days,
            "recurrence_count": self.recurrence,
            "reason": self.reason,
            "stats": self.stats.as_dict(),
        }


def _aware(moment: datetime) -> datetime:
    """Treat every naive timestamp as UTC.

    SQLite returns naive datetimes while the application works in UTC-aware
    ones, and an injected `now` may be either. Normalising at the boundary
    keeps deadline arithmetic from silently shifting by the local offset.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def assess(session: Session, grievance: Grievance, *, now: datetime) -> SlaAssessment:
    """Assess one open case against its deadline and the history."""
    policy = get_policy(session, grievance.category_id)
    moment = _aware(now)
    due = _aware(grievance.sla_due_at)
    hours_remaining = (due - moment).total_seconds() / 3600

    stats = duration_stats(
        session,
        category_id=grievance.category_id,
        department_id=grievance.department_id,
        sla_days=policy.sla_days,
    )
    recurrence = recurrence_count(
        session,
        category_id=grievance.category_id,
        locality=grievance.locality,
        taluka=grievance.taluka,
    )

    elapsed_days = (moment - _aware(grievance.created_at)).total_seconds() / 86400

    escalation_window = policy.sla_days * 24 * ESCALATION_REMAINING_FRACTION

    if hours_remaining < 0:
        risk = RISK_OVERDUE
        reason = (
            f"Past the {policy.sla_days}-day deadline by "
            f"{abs(hours_remaining) / 24:.1f} day(s)."
        )
    elif not stats.usable:
        # Thin history must not become a confident prediction. The deadline
        # still drives the alert.
        risk = RISK_AT_RISK if hours_remaining <= escalation_window else RISK_UNKNOWN
        reason = (
            f"Only {stats.sample_size} comparable closed case(s) in the history "
            f"({MIN_SAMPLES} needed), so no duration estimate is offered. "
            + (
                f"Flagged because {hours_remaining:.0f}h of the "
                f"{policy.sla_days}-day window remain."
                if risk == RISK_AT_RISK
                else "Monitoring against the deadline only."
            )
        )
    else:
        projected_days = max(stats.p80_days or 0.0, elapsed_days)
        if projected_days > policy.sla_days:
            risk = RISK_BREACH_LIKELY
            reason = (
                f"4 in 5 comparable cases took up to {stats.p80_days:.0f} day(s) "
                f"against a {policy.sla_days}-day SLA "
                f"(n={stats.sample_size}, {stats.basis}, "
                f"{(stats.breach_rate or 0) * 100:.0f}% historically breached)."
            )
        elif hours_remaining <= escalation_window:
            risk = RISK_AT_RISK
            reason = (
                f"{hours_remaining:.0f}h of the {policy.sla_days}-day window "
                f"remain; comparable cases typically take "
                f"{stats.p50_days:.0f} day(s) (n={stats.sample_size})."
            )
        else:
            risk = RISK_ON_TRACK
            reason = (
                f"Comparable cases typically close in {stats.p50_days:.0f} day(s) "
                f"against a {policy.sla_days}-day SLA (n={stats.sample_size})."
            )

    if recurrence >= RECURRENCE_MIN_CASES:
        reason += (
            f" This locality has produced {recurrence} past case(s) in the same "
            f"category, so the underlying issue may be recurring."
        )

    return SlaAssessment(
        reference_no=grievance.reference_no,
        risk=risk,
        hours_remaining=hours_remaining,
        due_at=due,
        sla_days=policy.sla_days,
        stats=stats,
        recurrence=recurrence,
        reason=reason,
    )


ESCALATING_RISKS = {RISK_BREACH_LIKELY, RISK_AT_RISK, RISK_OVERDUE}

#: Statuses that mean the case is still being worked. Anything else is done.
OPEN_STATUSES = frozenset(
    s.strip()
    for s in os.environ.get("OPEN_STATUSES", "Submitted,In Progress").split(",")
    if s.strip()
)


def scan(
    session: Session, *, now: datetime | None = None, raise_alerts: bool = True
) -> dict[str, Any]:
    """The scheduled job: assess every open case and raise escalation alerts.

    `now` is injectable because the supplied history runs into the future and
    a demo needs to show an alert arriving before a deadline, not after.

    An alert is raised once per case per risk level, so re-running the job
    does not spam the queue.
    """
    moment = _aware(now) if now else datetime.now(timezone.utc)
    open_cases = list(
        session.scalars(select(Grievance).where(Grievance.status.in_(OPEN_STATUSES)))
    )

    assessments: list[SlaAssessment] = []
    raised: list[dict[str, Any]] = []

    for grievance in open_cases:
        assessment = assess(session, grievance, now=moment)
        assessments.append(assessment)

        if not raise_alerts or assessment.risk not in ESCALATING_RISKS:
            continue

        already = session.scalar(
            select(SlaAlert).where(
                SlaAlert.grievance_id == grievance.id,
                SlaAlert.risk == assessment.risk,
            )
        )
        if already is not None:
            continue

        alert = SlaAlert(
            grievance_id=grievance.id,
            risk=assessment.risk,
            predicted_days=assessment.stats.p80_days if assessment.stats.usable else None,
            historical_p80_days=assessment.stats.p80_days,
            sample_size=assessment.stats.sample_size,
            sla_days=assessment.sla_days,
            due_at=assessment.due_at,
            raised_at=moment,
            reason=assessment.reason,
        )
        session.add(alert)
        session.flush()

        record_audit(
            session,
            build_audit_entry(
                actor=Actor.AI_SYSTEM,
                action="RAISE_SLA_ALERT",
                target=grievance.reference_no,
                reasoning=assessment.reason,
                model="sla-statistics",
                # A statistical alert is not a classification; its confidence
                # is the share of comparable cases behind it, or 0 when none.
                confidence=(
                    round(min(1.0, assessment.stats.sample_size / 50), 2)
                    if assessment.stats.usable
                    else 0.0
                ),
                rule_applied="RULE_7_SLA_ESCALATION_BEFORE_DEADLINE",
                timestamp=moment,
            ),
        )
        raised.append(assessment.as_dict())

    session.commit()
    return {
        "scanned_at": moment.isoformat(),
        "open_cases": len(open_cases),
        "alerts_raised": len(raised),
        "raised": raised,
        "assessments": [a.as_dict() for a in assessments],
    }
