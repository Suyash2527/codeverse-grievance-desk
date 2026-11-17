"""Policy Agent.

Reads the Sensitive flag, the Identity-Hiding flag and the configured
confidence threshold from the category master, and returns either
AUTO_RESOLVE or HUMAN_QUEUE together with the exact rule that applied.

This node contains no model call. The gate is arithmetic over flags, which is
what makes it reproducible and testable, and what stops a persuasive model
output from unlocking an automated closure.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.config import settings
from app.observability.trace import POLICY_SPAN, record, span
from app.policy.guards import (
    GateOutcome,
    apply_precautionary_hold,
    evaluate_policy_gate,
)
from app.policy.sensitive_signals import sensitive_wording_matches
from app.policy.store import UnknownCategoryError, get_policy


def _sensitive_neighbours(session: Session, state: PipelineState) -> list[dict]:
    """Retrieved cases whose own category is flagged sensitive in the master.

    Sensitivity is read from the master for each neighbour's category, never
    from the historical row's copied flag, so a stale history column cannot
    weaken or strengthen this check.
    """
    neighbours = state.get("intake_neighbours") or []
    out: list[dict] = []
    for neighbour in neighbours:
        category_id = neighbour.get("category_id")
        if not category_id:
            continue
        try:
            if get_policy(session, category_id).sensitive:
                out.append(neighbour)
        except UnknownCategoryError:
            continue
    return out


def run_policy(session: Session, state: PipelineState) -> PipelineState:
    draft = state.get("draft") or {}
    category_id = draft.get("category_id")
    confidence = float(state.get("intake_confidence") or 0.0)
    threshold = settings.confidence_threshold

    with span(POLICY_SPAN, category_id=category_id, confidence=confidence) as current:
        if not category_id:
            # No category means policy cannot be established. That is never
            # resolved by guessing; it goes to a human.
            gate = {
                "outcome": GateOutcome.HUMAN_QUEUE.value,
                "rule_applied": "CATEGORY_UNDETERMINED_REQUIRES_HUMAN_REVIEW",
                "reason": (
                    "The intake agent could not map the complaint to a category "
                    "in the master, so the sensitivity of the case is unknown."
                ),
                "confidence": confidence,
                "threshold": threshold,
                "sensitive": None,
                "identity_hiding": None,
                "policy_note": "",
            }
        else:
            try:
                policy = get_policy(session, category_id)
            except UnknownCategoryError as exc:
                gate = {
                    "outcome": GateOutcome.HUMAN_QUEUE.value,
                    "rule_applied": "CATEGORY_NOT_IN_MASTER_REQUIRES_HUMAN_REVIEW",
                    "reason": str(exc),
                    "confidence": confidence,
                    "threshold": threshold,
                    "sensitive": None,
                    "identity_hiding": None,
                    "policy_note": "",
                }
            else:
                decision = evaluate_policy_gate(
                    policy, confidence=confidence, threshold=threshold
                )
                # The guard above trusts the chosen category. When the
                # classifier is wrong downward — calling a sparking live wire
                # "footpath damage" — nothing would stop automation, so the
                # retrieved evidence gets a second, one-directional say.
                decision = apply_precautionary_hold(
                    decision,
                    sensitive_neighbours=_sensitive_neighbours(session, state),
                    wording_matches=sensitive_wording_matches(
                        session,
                        f"{state.get('raw_text', '')} "
                        f"{(state.get('draft') or {}).get('description') or ''}",
                    ),
                )
                gate = {
                    "outcome": decision.outcome.value,
                    "rule_applied": decision.rule_applied,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "threshold": decision.threshold,
                    "sensitive": policy.sensitive,
                    "identity_hiding": policy.identity_hiding,
                    "policy_note": policy.policy_note,
                }
        record(current, **gate)

    state["gate"] = gate
    return state
