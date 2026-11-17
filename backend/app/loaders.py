"""Load the supplied CSVs into the configuration tables.

Loading is a full replace, not a merge: dropping the old rows and inserting
the new file is what makes "swap a CSV, behaviour changes" true with no code
edit and no stale policy left behind.

Referential gaps are reported, not fatal. The supplied directory contains one
department (D009) that no category routes to, which is legitimate data, and a
replacement CSV may legitimately reference departments differently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings, settings as default_settings
from app.csvdata import (
    parse_category_master,
    parse_department_directory,
    parse_grievance_history,
)
from app.models import CategoryMaster, DepartmentDirectory, GrievanceHistory


@dataclass
class LoadReport:
    categories: int = 0
    departments: int = 0
    history: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "categories": self.categories,
            "departments": self.departments,
            "history": self.history,
            "warnings": self.warnings,
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def load_category_master(session: Session, settings: Settings) -> int:
    rows = parse_category_master(settings.category_master_csv)
    session.execute(delete(CategoryMaster))
    session.add_all(
        CategoryMaster(
            category_id=r.category_id,
            category=r.category,
            subcategory=r.subcategory,
            responsible_department_id=r.responsible_department_id,
            responsible_department=r.responsible_department,
            default_assignee=r.default_assignee,
            sla_days=r.sla_days,
            sensitive=r.sensitive,
            identity_hiding=r.identity_hiding,
            default_priority=r.default_priority,
            auto_resolution_allowed=r.auto_resolution_allowed,
            policy_note=r.policy_note,
        )
        for r in rows
    )
    return len(rows)


def load_department_directory(session: Session, settings: Settings) -> int:
    rows = parse_department_directory(settings.department_directory_csv)
    session.execute(delete(DepartmentDirectory))
    session.add_all(
        DepartmentDirectory(
            department_id=r.department_id,
            department_name=r.department_name,
            service_scope=r.service_scope,
            jurisdiction_type=r.jurisdiction_type,
            jurisdiction_mapping=r.jurisdiction_mapping,
            jurisdiction_talukas=r.jurisdiction_talukas,
            contact_email_demo=r.contact_email_demo,
            contact_channel=r.contact_channel,
            mock_webhook_id=r.mock_webhook_id,
            is_real_contact=r.is_real_contact,
            notes=r.notes,
        )
        for r in rows
    )
    return len(rows)


def load_grievance_history(session: Session, settings: Settings) -> int:
    rows = parse_grievance_history(settings.grievance_history_csv)
    session.execute(delete(GrievanceHistory))
    objects = []
    for r in rows:
        submitted = _parse_date(r.submission_date)
        resolved = _parse_date(r.resolution_date)
        resolution_days = (resolved - submitted).days if submitted and resolved else None
        objects.append(
            GrievanceHistory(
                grievance_id=r.grievance_id,
                complaint_text=r.complaint_text,
                category_id=r.category_id,
                category=r.category,
                subcategory=r.subcategory,
                department_id=r.department_id,
                broad_location_taluka=r.broad_location_taluka,
                broad_location_locality=r.broad_location_locality,
                submission_date=submitted,
                resolution_date=resolved,
                status=r.status,
                resolution_text=r.resolution_text,
                citizen_feedback=r.citizen_feedback,
                priority=r.priority,
                sla_days=r.sla_days,
                sensitive=r.sensitive,
                identity_hiding=r.identity_hiding,
                resolution_actor=r.resolution_actor,
                ai_auto_closed=r.ai_auto_closed,
                data_origin=r.data_origin,
                resolution_days=resolution_days,
            )
        )
    session.add_all(objects)
    return len(objects)


def check_referential_integrity(session: Session) -> list[str]:
    """Report join gaps without failing the load."""
    warnings: list[str] = []
    dept_ids = set(session.scalars(select(DepartmentDirectory.department_id)))
    cat_ids = set(session.scalars(select(CategoryMaster.category_id)))

    for cid, did in session.execute(
        select(CategoryMaster.category_id, CategoryMaster.responsible_department_id)
    ):
        if did not in dept_ids:
            warnings.append(
                f"category {cid} routes to unknown department {did!r}; "
                f"routing for it will fall back to the coordination queue"
            )

    referenced = set(
        session.scalars(select(CategoryMaster.responsible_department_id).distinct())
    )
    for orphan in sorted(dept_ids - referenced):
        warnings.append(
            f"department {orphan} is in the directory but no category routes to it"
        )

    hist_cats = set(session.scalars(select(GrievanceHistory.category_id).distinct()))
    for missing in sorted(hist_cats - cat_ids):
        warnings.append(
            f"history references category {missing!r} which is not in the "
            f"category master; its past cases cannot be policy-checked"
        )
    return warnings


def reload_reference_data(
    session: Session,
    settings: Settings | None = None,
    *,
    include_history: bool = True,
) -> LoadReport:
    """Replace all configuration tables from the CSVs in DATA_DIR."""
    cfg = settings or default_settings
    report = LoadReport()
    report.categories = load_category_master(session, cfg)
    report.departments = load_department_directory(session, cfg)
    if include_history:
        report.history = load_grievance_history(session, cfg)
    session.flush()
    report.warnings = check_referential_integrity(session)
    session.commit()
    return report
