"""Demo scenario 1: a routine case that follows the allowed automated path.

    python scripts/seed_scenario_1_routine.py

Expected: a non-sensitive category, confidence at or above the threshold,
gate AUTO_RESOLVE, status Resolved, department webhook dispatched as a mock,
and a Langfuse trace link when tracing is configured.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts._scenario import print_outcome, run_scenario  # noqa: E402

COMPLAINT = (
    "Pipeline leakage is wasting a lot of water on the main road near the "
    "market in Mukhed since yesterday."
)


def main() -> int:
    state = run_scenario(
        label="Scenario 1 - routine case, automated path",
        raw_text=COMPLAINT,
        taluka="Mukhed",
        locality="Mukhed Town",
        citizen_name="Demo Citizen One",
        citizen_phone="0000000001",
    )
    return print_outcome(
        state,
        expect_gate="AUTO_RESOLVE",
        expect_status="Resolved",
    )


if __name__ == "__main__":
    raise SystemExit(main())
