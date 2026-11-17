"""Shared state passed between agents in the graph."""
from __future__ import annotations

from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """What flows through Intake -> Retrieval -> Policy -> Decision -> Action.

    Kept as a plain TypedDict so a node can be called directly in a test
    without constructing the whole graph.
    """

    # Input
    raw_text: str
    language: str
    taluka: str | None
    locality: str | None
    citizen_name: str | None
    citizen_phone: str | None
    citizen_email: str | None
    grievance_ref: str | None

    # Intake
    draft: dict[str, Any]
    missing_details: list[str]
    intake_confidence: float
    model: str
    #: Similar past cases considered while choosing the category. Used for the
    #: precautionary sensitive check; never to justify automation.
    intake_neighbours: list[dict[str, Any]]

    # Retrieval
    evidence: dict[str, Any]
    retrieved_case_ids: list[str]

    # Summary (officer-facing, labelled AI output)
    ai_summary: dict[str, Any]
    ai_sentiment: dict[str, Any]

    # Policy
    gate: dict[str, Any]

    # Decision
    decision: dict[str, Any]

    # Action
    actions: list[dict[str, Any]]

    # Cross-cutting
    errors: list[str]
    trace_url: str | None
