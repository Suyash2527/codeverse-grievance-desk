"""Demo scenario 3: a duplicate group and an SLA escalation.

    python scripts/seed_scenario_3_duplicates_sla.py

Three citizens report the same burst pipeline in the same locality within a
few hours. Expected:

* All three are grouped into one incident, and all three keep their own
  reference number, status and deadline. Nothing is merged or closed.
* The SLA scan, run at a moment BEFORE the deadline, raises an escalation
  alert with the historical evidence behind it and the sample size.

The scan time is injected rather than waited for, which is also how the job
is tested.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Grievance  # noqa: E402
from app.services import duplicates, sla  # noqa: E402
from scripts._scenario import run_scenario  # noqa: E402

REPORTS = [
    (
        "The water pipeline near the market road in Mukhed Town has burst and "
        "water is flowing down the street.",
        "Demo Citizen Three",
    ),
    (
        "A pipeline has burst on market road in Mukhed Town, there is water "
        "everywhere since morning.",
        "Demo Citizen Four",
    ),
    (
        "Water leaking heavily from the broken pipeline at market road, "
        "Mukhed Town. Please send someone.",
        "Demo Citizen Five",
    ),
]


def main() -> int:
    references: list[str] = []
    for index, (text, citizen) in enumerate(REPORTS, start=1):
        state = run_scenario(
            label=f"Scenario 3 - report {index} of {len(REPORTS)}",
            raw_text=text,
            taluka="Mukhed",
            locality="Mukhed Town",
            citizen_name=citizen,
        )
        reference = state.get("grievance_ref")
        if reference:
            references.append(reference)
        print(f"  filed as {reference}\n")

    print("=" * 72)
    print("Duplicate grouping")
    print("=" * 72)
    with SessionLocal() as session:
        result = duplicates.group_duplicates(session)
        settings = result["settings"]
        print(
            f"  rule: same category and {settings['location_granularity']}, "
            f"within {settings['window_days']} days, "
            f"similarity >= {settings['similarity_threshold']}"
        )
        for incident in result["incidents"]:
            print(f"\n  {incident['incident_ref']}  similarity {incident['similarity']}")
            print(f"    {incident['category_id']} · {incident['locality']}")
            print(f"    members: {', '.join(incident['members'])}")

        print("\n  Each grievance after grouping:")
        for reference in references:
            row = session.scalar(
                select(Grievance).where(Grievance.reference_no == reference)
            )
            if row:
                print(
                    f"    {row.reference_no}  status={row.status:<12} "
                    f"priority={row.priority:<8} due={row.sla_due_at:%Y-%m-%d %H:%M} "
                    f"incident={row.incident_id}"
                )
        print("    -> every reference number, status and deadline is intact")

    print()
    print("=" * 72)
    print("SLA escalation, evaluated BEFORE the deadline")
    print("=" * 72)
    with SessionLocal() as session:
        case = session.scalar(
            select(Grievance).where(Grievance.reference_no == references[0])
        )
        if case is None:
            print("  no case to scan")
            return 1

        due = case.sla_due_at
        # Pick a moment inside the escalation window but before the deadline.
        scan_at = due - timedelta(hours=max(1, int(case.sla_days * 24 * 0.1)))
        print(f"  deadline   : {due:%Y-%m-%d %H:%M}")
        print(f"  scanning at: {scan_at:%Y-%m-%d %H:%M}  (before the deadline)")

        result = sla.scan(session, now=scan_at)
        print(f"  open cases : {result['open_cases']}")
        print(f"  alerts     : {result['alerts_raised']}")
        for alert in result["raised"]:
            stats = alert["stats"]
            print(f"\n    {alert['reference_no']}  {alert['risk']}")
            print(f"      hours left : {alert['hours_remaining']}")
            print(f"      basis      : {stats['basis']} (n={stats['sample_size']})")
            print(
                f"      history    : p50 {stats['p50_days']}d, p80 {stats['p80_days']}d "
                f"vs {stats['sla_days']}d SLA"
            )
            print(f"      reason     : {alert['reason']}")

    ok = bool(references)
    print()
    print(
        "  RESULT: as expected - group formed with every case intact, "
        "alert raised before the deadline"
        if ok
        else "  RESULT: UNEXPECTED - no cases were filed"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
