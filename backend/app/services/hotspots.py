"""Taluka hotspot analytics.

Answers "where are the problems concentrated, and where is the district
missing its own deadlines" by aggregating live cases and historical ones per
taluka.

Two privacy rules shape this module, both from the dataset guide:

* Aggregation stops at **taluka**. Localities are never exposed here, because
  a locality plus a sensitive category can identify a household.
* Any figure derived from an Identity-Hiding category is **suppressed below a
  minimum cell size** (k-anonymity). A count of 1 sensitive case in a small
  taluka is a disclosure, not a statistic.

Nothing here carries a reference number or a complainant detail.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CategoryMaster, DepartmentDirectory, Grievance, GrievanceHistory
from app.services.sla import OPEN_STATUSES

#: Minimum number of cases before a figure drawn from an identity-hiding
#: category is reported. Below this it is suppressed.
MIN_CELL_SIZE = int(os.environ.get("ANALYTICS_MIN_CELL_SIZE", "3"))

SUPPRESSED = "suppressed"


@dataclass
class TalukaRow:
    taluka: str
    live_open: int
    live_overdue: int
    live_total: int
    historical_total: int
    historical_breached: int
    historical_breach_rate: float | None
    top_categories: list[dict[str, Any]]
    sensitive_cases: int | str
    recurring_categories: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _known_talukas(session: Session) -> list[str]:
    """Every taluka the loaded data knows about, not only ones with cases.

    A taluka with zero complaints is a finding too: either genuinely quiet or
    not reaching the system at all.
    """
    from app.services.geo import known_talukas

    return known_talukas(session)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def hotspots(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Per-taluka aggregates, ordered by live pressure then historical failure."""
    moment = _aware(now) or datetime.now(timezone.utc)

    sensitive_categories = {
        row
        for row in session.scalars(
            select(CategoryMaster.category_id).where(
                CategoryMaster.identity_hiding.is_(True)
            )
        )
    }
    category_names = {
        row.category_id: f"{row.category} / {row.subcategory}"
        for row in session.scalars(select(CategoryMaster))
    }

    rows: list[TalukaRow] = []
    for taluka in _known_talukas(session):
        live = list(
            session.scalars(select(Grievance).where(Grievance.taluka == taluka))
        )
        open_cases = [g for g in live if g.status in OPEN_STATUSES]
        overdue = [
            g
            for g in open_cases
            if g.sla_due_at and (_aware(g.sla_due_at) or moment) < moment
        ]

        history = list(
            session.scalars(
                select(GrievanceHistory).where(
                    GrievanceHistory.broad_location_taluka == taluka
                )
            )
        )
        closed = [h for h in history if h.resolution_days is not None]
        breached = [h for h in closed if h.resolution_days > h.sla_days]

        # Category mix, drawn from history plus live cases.
        counts: dict[str, int] = {}
        for item in history:
            counts[item.category_id] = counts.get(item.category_id, 0) + 1
        for item in live:
            counts[item.category_id] = counts.get(item.category_id, 0) + 1

        top = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:3]
        top_categories = [
            {
                "category_id": category_id,
                "label": category_names.get(category_id, category_id),
                "count": count,
                # A sensitive category is named only once enough cases exist
                # that naming it identifies nobody.
                "suppressed": category_id in sensitive_categories
                and count < MIN_CELL_SIZE,
            }
            for category_id, count in top
        ]
        for entry in top_categories:
            if entry["suppressed"]:
                entry["label"] = "Sensitive category (withheld, small count)"
                entry["category_id"] = SUPPRESSED
                entry["count"] = SUPPRESSED

        sensitive_total = sum(
            count
            for category_id, count in counts.items()
            if category_id in sensitive_categories
        )

        recurring = [
            category_names.get(category_id, category_id)
            for category_id, count in counts.items()
            if count >= MIN_CELL_SIZE and category_id not in sensitive_categories
        ]

        rows.append(
            TalukaRow(
                taluka=taluka,
                live_open=len(open_cases),
                live_overdue=len(overdue),
                live_total=len(live),
                historical_total=len(history),
                historical_breached=len(breached),
                historical_breach_rate=(
                    round(len(breached) / len(closed), 3) if closed else None
                ),
                top_categories=top_categories,
                sensitive_cases=(
                    sensitive_total if sensitive_total >= MIN_CELL_SIZE else SUPPRESSED
                ),
                recurring_categories=sorted(recurring)[:4],
            )
        )

    rows.sort(
        key=lambda row: (
            row.live_overdue,
            row.live_open,
            row.historical_breach_rate or 0,
        ),
        reverse=True,
    )

    district_closed = session.scalar(
        select(func.count())
        .select_from(GrievanceHistory)
        .where(GrievanceHistory.resolution_days.isnot(None))
    )
    district_breached = session.scalar(
        select(func.count())
        .select_from(GrievanceHistory)
        .where(GrievanceHistory.resolution_days > GrievanceHistory.sla_days)
    )

    return {
        "generated_at": moment.isoformat(),
        "talukas": [row.as_dict() for row in rows],
        "district": {
            "talukas_covered": len(rows),
            "historical_closed": district_closed,
            "historical_breached": district_breached,
            "historical_breach_rate": (
                round(district_breached / district_closed, 3) if district_closed else None
            ),
            "live_open": session.scalar(
                select(func.count())
                .select_from(Grievance)
                .where(Grievance.status.in_(OPEN_STATUSES))
            ),
        },
        "privacy": {
            "granularity": "taluka",
            "min_cell_size": MIN_CELL_SIZE,
            "note": (
                "Aggregated to taluka only. Figures drawn from identity-hiding "
                "categories are withheld below the minimum cell size, and no "
                "reference number or complainant detail appears in this view."
            ),
        },
    }
