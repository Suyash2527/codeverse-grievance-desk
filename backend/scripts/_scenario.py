"""Shared harness for the demo seed scripts.

Each scenario runs the real pipeline against the configured database and
prints what a judge needs to see: the category chosen, the policy rule that
applied, the evidence used, the resulting status and the trace link.

The scripts assert their expected outcome and exit non-zero if it does not
hold, so they double as end-to-end checks rather than just demos.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import AuditLog, CategoryMaster, GrievanceHistory
from app.observability.trace import tracing_enabled


def _ensure_data_loaded() -> None:
    """Load the CSVs if the database is empty, so a scenario runs standalone."""
    from app.config import settings
    from app.loaders import reload_reference_data

    init_db()
    with SessionLocal() as session:
        if session.scalar(select(CategoryMaster).limit(1)) is None:
            print("  (loading reference data first)")
            reload_reference_data(session, settings)


def run_scenario(
    *,
    label: str,
    raw_text: str,
    taluka: str | None = None,
    locality: str | None = None,
    language: str = "en",
    citizen_name: str | None = None,
    citizen_phone: str | None = None,
) -> dict[str, Any]:
    from app.agents.graph import run_pipeline

    print("=" * 72)
    print(label)
    print("=" * 72)
    _ensure_data_loaded()

    with SessionLocal() as session:
        embedded = session.scalar(
            select(GrievanceHistory.grievance_id)
            .where(GrievanceHistory.embedding.isnot(None))
            .limit(1)
        )
        if not embedded:
            print(
                "  note: history is not embedded yet, so retrieval will use the "
                "keyword fallback. Run scripts/embed_history.py for semantic "
                "retrieval."
            )
        print(f"\n  Complaint: {raw_text}\n")
        return run_pipeline(
            session,
            raw_text=raw_text,
            language=language,
            taluka=taluka,
            locality=locality,
            citizen_name=citizen_name,
            citizen_phone=citizen_phone,
        )


def print_outcome(
    state: dict[str, Any], *, expect_gate: str, expect_status: str
) -> int:
    draft = state.get("draft") or {}
    gate = state.get("gate") or {}
    decision = state.get("decision") or {}
    evidence = state.get("evidence") or {}
    reference = state.get("grievance_ref")

    print("  Intake")
    print(f"    category      : {draft.get('category_id')}")
    print(f"    confidence    : {gate.get('confidence')}  (threshold {gate.get('threshold')})")
    print(f"    missing       : {state.get('missing_details') or 'none'}")

    print("  Retrieval")
    print(f"    method        : {evidence.get('method')}")
    print(f"    cases         : {[c['grievance_id'] for c in evidence.get('cases', [])]}")
    print("    note          : evidence only; it does not decide the outcome")

    print("  Policy gate")
    print(f"    outcome       : {gate.get('outcome')}")
    print(f"    rule applied  : {gate.get('rule_applied')}")
    print(f"    reason        : {gate.get('reason')}")
    print(f"    sensitive     : {gate.get('sensitive')}")
    print(f"    identity_hide : {gate.get('identity_hiding')}")

    print("  Decision")
    print(f"    reference     : {reference}")
    print(f"    priority      : {decision.get('priority')} (score {decision.get('priority_score', 0):.2f})")
    print(f"    department    : {decision.get('department_id')} / {decision.get('assignee')}")

    print("  Actions")
    for action in state.get("actions") or []:
        detail = action.get("status") or action.get("channel") or action.get("destination") or ""
        flag = "ok" if action.get("ok") else f"REFUSED {action.get('refused_rule', '')}"
        print(f"    {action['action']:<14} {detail:<22} {flag}")

    status = None
    if reference:
        with SessionLocal() as session:
            from app.models import Grievance

            row = session.query(Grievance).filter_by(reference_no=reference).one_or_none()
            status = row.status if row else None
            audits = session.scalars(
                select(AuditLog).where(AuditLog.target == reference)
            ).all()
        print("  Audit trail")
        for entry in audits:
            print(
                f"    {entry.actor:<10} {entry.action:<34} "
                f"model={entry.model or '-'} conf={entry.confidence} "
                f"rule={entry.rule_applied}"
            )

    print("  Observability")
    if tracing_enabled():
        print(f"    trace         : {state.get('trace_url') or 'created (see Langfuse)'}")
    else:
        print("    trace         : tracing disabled (LANGFUSE_* not set)")

    ok = gate.get("outcome") == expect_gate and status == expect_status
    print()
    if ok:
        print(f"  RESULT: as expected - gate {expect_gate}, status {expect_status}")
        return 0
    print(
        f"  RESULT: UNEXPECTED - gate {gate.get('outcome')} (wanted {expect_gate}), "
        f"status {status} (wanted {expect_status})"
    )
    return 1
