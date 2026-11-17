"""Reading policy from the live category master.

Every guard call needs a PolicySnapshot, and it must come from the currently
loaded master rather than from flags copied onto a ticket. This module is the
only place that bridges the database to the guard layer, so there is one
answer to "where did this policy come from".
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CategoryMaster, DepartmentDirectory
from app.policy.guards import PolicySnapshot


class UnknownCategoryError(LookupError):
    """Raised when a category_id is not present in the loaded master.

    This is never silently defaulted: an unknown category means the system
    cannot establish whether the case is sensitive, so it must not proceed
    automatically.
    """


def get_category(session: Session, category_id: str) -> CategoryMaster:
    row = session.get(CategoryMaster, category_id)
    if row is None:
        raise UnknownCategoryError(
            f"category {category_id!r} is not in the loaded category master; "
            f"policy cannot be established, so the case requires human review"
        )
    return row


def get_policy(session: Session, category_id: str) -> PolicySnapshot:
    """Return the live policy snapshot for a category."""
    row = get_category(session, category_id)
    return PolicySnapshot(
        category_id=row.category_id,
        sensitive=row.sensitive,
        identity_hiding=row.identity_hiding,
        auto_resolution_allowed=row.auto_resolution_allowed,
        sla_days=row.sla_days,
        default_priority=row.default_priority,
        responsible_department_id=row.responsible_department_id,
        default_assignee=row.default_assignee,
        policy_note=row.policy_note,
    )


def get_department(session: Session, department_id: str) -> DepartmentDirectory | None:
    return session.get(DepartmentDirectory, department_id)


def list_categories(session: Session) -> list[CategoryMaster]:
    return list(session.scalars(select(CategoryMaster).order_by(CategoryMaster.category_id)))


def list_departments(session: Session) -> list[DepartmentDirectory]:
    return list(
        session.scalars(
            select(DepartmentDirectory).order_by(DepartmentDirectory.department_id)
        )
    )
