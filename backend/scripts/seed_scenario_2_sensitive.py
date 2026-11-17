"""Demo scenario 2: a sensitive case held for human review.

    python scripts/seed_scenario_2_sensitive.py

Expected: a sensitive category, gate HUMAN_QUEUE citing
RULE_1_SENSITIVE_NEVER_AUTO_CLOSED, status In Progress rather than Resolved,
and the citizen identity masked in the department-facing payload.

The script then attempts an automated closure directly, to show the refusal
and the audit entry it leaves behind.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import Grievance  # noqa: E402
from app.policy.guards import Actor, Audience, PolicyViolation  # noqa: E402
from app.services.grievance_service import (  # noqa: E402
    record_audit,
    serialize_grievance,
    update_status,
)
from app.policy.guards import build_refusal_audit_entry  # noqa: E402
from scripts._scenario import print_outcome, run_scenario  # noqa: E402

COMPLAINT = (
    "Please arrange a confidential child safety protection review for a "
    "concern reported in Bahadarpura. I do not want my name shared."
)


def attempt_auto_close(reference_no: str) -> None:
    """Show the guard refusing an automated closure, and the audit it leaves."""
    with SessionLocal() as session:
        grievance = (
            session.query(Grievance).filter_by(reference_no=reference_no).one_or_none()
        )
        if grievance is None:
            return
        print("\n  Attempting an automated closure of the sensitive case:")
        try:
            update_status(
                session,
                grievance=grievance,
                new_status="Closed",
                actor=Actor.AI_SYSTEM,
                model="demo-script",
                confidence=0.99,
                reasoning="scripted attempt to auto-close a sensitive case",
            )
            print("    UNEXPECTED: the closure was allowed")
        except PolicyViolation as exc:
            session.rollback()
            record_audit(
                session,
                build_refusal_audit_entry(
                    actor=Actor.AI_SYSTEM,
                    attempted_action="UPDATE_STATUS_TO_CLOSED",
                    target=reference_no,
                    violation=exc,
                    model="demo-script",
                    confidence=0.99,
                ),
            )
            session.commit()
            print(f"    REFUSED  : {exc.rule}")
            print(f"    detail   : {exc}")

        department_view = serialize_grievance(
            session, grievance, audience=Audience.DEPARTMENT
        )
        print("\n  Department-facing payload:")
        print(f"    citizen_name   : {department_view['citizen_name']}")
        print(f"    citizen_phone  : {department_view['citizen_phone']}")
        print(f"    identity_masked: {department_view['identity_masked']}")
        print(f"    status         : {department_view['status']}")


def main() -> int:
    state = run_scenario(
        label="Scenario 2 - sensitive case, human review",
        raw_text=COMPLAINT,
        taluka="Kandhar",
        locality="Bahadarpura",
        citizen_name="Demo Citizen Two",
        citizen_phone="0000000002",
    )
    code = print_outcome(
        state,
        expect_gate="HUMAN_QUEUE",
        expect_status="In Progress",
    )
    if state.get("grievance_ref"):
        attempt_auto_close(state["grievance_ref"])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
