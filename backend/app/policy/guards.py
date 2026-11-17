"""Deterministic enforcement of the eight hard rules.

These are judged pass/fail, so none of them is left to an LLM prompt. Every
rule is a pure function over a policy snapshot taken from the category master
at decision time, and every write path in the system is required to call
through here.

The rules, and where each is enforced:

1. A Sensitive case is never auto-closed       -> authorize_status_change
2. The AI never auto-rejects, never rules on liability
                                               -> authorize_status_change (allow-list)
3. Identity-Hiding categories are masked in
   department-facing views, webhooks, notices  -> mask_identity
4. Every AI action is audited with actor,
   model, confidence, timestamp, reasoning     -> build_audit_entry
5. Every decision stores confidence, the
   retrieved cases and the exact rule applied  -> build_decision_record
6. AI output is labelled, never a verified fact -> label_ai_output
7. Priority = severity + urgency + affected
   population, never raw submission count      -> compute_priority / PriorityInputs
8. Contacts are mock placeholders; nothing is
   ever sent to a real address                 -> assert_mock_destination

Nothing about a specific category, department, SLA or taluka appears in this
module. It reads whatever the loaded master says.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from app.csvdata import CategoryRow

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

#: Statuses that end a case. Configurable because a replacement dataset may
#: use a different workflow vocabulary; the supplied history uses
#: Submitted / In Progress / Resolved / Closed.
CLOSING_STATUSES: frozenset[str] = frozenset(
    s.strip()
    for s in os.environ.get("CLOSING_STATUSES", "Resolved,Closed").split(",")
    if s.strip()
)

#: The only statuses an automated actor may ever set. This is an allow-list,
#: not a deny-list of rejection words: any status outside it (Rejected,
#: Dismissed, Invalid, Not Admissible, anything a future CSV invents) is
#: refused for AI actors, which is what makes rule 2 hold without guessing
#: at rejection vocabulary.
AI_ALLOWED_STATUSES: frozenset[str] = frozenset(
    s.strip()
    for s in os.environ.get(
        "AI_ALLOWED_STATUSES", "Submitted,In Progress,Resolved,Closed"
    ).split(",")
    if s.strip()
)

PRIORITY_ORDER: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

AI_LABEL = "AI-generated"


class Actor(str, Enum):
    """Who is performing an action. Audit entries are written per actor."""

    AI_SYSTEM = "AI_SYSTEM"
    OFFICER = "OFFICER"
    CITIZEN = "CITIZEN"


class Audience(str, Enum):
    """Who is reading a grievance payload.

    DEPARTMENT, WEBHOOK and NOTIFICATION are external-facing and are masked for
    Identity-Hiding categories. CITIZEN_SELF is the complainant reading their
    own case, which is never masked from them.
    """

    DEPARTMENT = "DEPARTMENT"
    WEBHOOK = "WEBHOOK"
    NOTIFICATION = "NOTIFICATION"
    CITIZEN_SELF = "CITIZEN_SELF"


MASKED_AUDIENCES = frozenset(
    {Audience.DEPARTMENT, Audience.WEBHOOK, Audience.NOTIFICATION}
)

#: Fields that identify a complainant. Masked for Identity-Hiding categories.
IDENTITY_FIELDS: frozenset[str] = frozenset(
    {
        "citizen_name",
        "citizen_phone",
        "citizen_email",
        "citizen_contact_id",
        "reporter_name",
        "locality",
        "broad_location_locality",
        "address",
    }
)

MASK_PLACEHOLDER = "[WITHHELD - identity-hiding category]"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class PolicyViolation(Exception):
    """Base class. Carries the rule that was violated for the audit log."""

    rule: str = "UNSPECIFIED"

    def __init__(self, message: str, *, rule: str | None = None) -> None:
        super().__init__(message)
        if rule:
            self.rule = rule


class SensitiveAutoCloseError(PolicyViolation):
    rule = "RULE_1_SENSITIVE_NEVER_AUTO_CLOSED"


class AutoRejectionError(PolicyViolation):
    rule = "RULE_2_AI_NEVER_REJECTS_OR_RULES_ON_LIABILITY"


class ConfidenceBelowThresholdError(PolicyViolation):
    rule = "RULE_5_DECISION_BELOW_CONFIDENCE_THRESHOLD"


class PrecautionarySensitiveError(PolicyViolation):
    """Raised when similar past cases suggest this one may be sensitive.

    The classifier can be wrong about the category, and when it is wrong
    downward — calling a sparking live wire "footpath damage" — the sensitive
    guard never fires, because the guard trusts the category. This closes that
    gap from the other side: if the retrieved evidence points at a sensitive
    category, automation is withheld even though the chosen category permits
    it.

    Evidence is used asymmetrically on purpose. It may only ever make the
    system more cautious. No amount of evidence can unlock an automated
    closure, which is what keeps rule 1 intact.
    """

    rule = "PRECAUTIONARY_SENSITIVE_NEIGHBOUR_HUMAN_REVIEW"


class AutoResolutionNotAllowedError(PolicyViolation):
    rule = "CATEGORY_AUTO_RESOLUTION_NOT_ALLOWED"


class RealContactError(PolicyViolation):
    rule = "RULE_8_MOCK_CONTACTS_ONLY"


class IncompleteAuditError(PolicyViolation):
    rule = "RULE_4_AI_ACTIONS_FULLY_AUDITED"


class IncompleteDecisionError(PolicyViolation):
    rule = "RULE_5_DECISION_EVIDENCE_REQUIRED"


# --------------------------------------------------------------------------
# Policy snapshot
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicySnapshot:
    """The policy for one category, read from the master at decision time.

    Built from whatever CSV is currently loaded. The three flags are evaluated
    independently: in the supplied file they happen to coincide, but a
    replacement file may mark a category Identity-Hiding without marking it
    Sensitive, and the guards must behave correctly when it does.
    """

    category_id: str
    sensitive: bool
    identity_hiding: bool
    auto_resolution_allowed: bool
    sla_days: int
    default_priority: str
    responsible_department_id: str
    default_assignee: str
    policy_note: str = ""

    @classmethod
    def from_category_row(cls, row: CategoryRow) -> "PolicySnapshot":
        return cls(
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


class GateOutcome(str, Enum):
    AUTO_RESOLVE = "AUTO_RESOLVE"
    HUMAN_QUEUE = "HUMAN_QUEUE"


@dataclass(frozen=True)
class GateDecision:
    outcome: GateOutcome
    rule_applied: str
    reason: str
    confidence: float
    threshold: float
    policy_note: str = ""

    @property
    def requires_human(self) -> bool:
        return self.outcome is GateOutcome.HUMAN_QUEUE


# --------------------------------------------------------------------------
# Rule 1 + 2 + 5: the policy gate and the status-change guard
# --------------------------------------------------------------------------


def evaluate_policy_gate(
    policy: PolicySnapshot, *, confidence: float, threshold: float
) -> GateDecision:
    """Decide between automated resolution and the human queue.

    Checks run in a fixed order so the reported rule is the most important one
    that applied, and so a Sensitive case can never fall through to
    auto-resolution because of a high confidence score.
    """
    if policy.sensitive:
        return GateDecision(
            outcome=GateOutcome.HUMAN_QUEUE,
            rule_applied=SensitiveAutoCloseError.rule,
            reason=(
                f"Category {policy.category_id} is flagged sensitive in the "
                f"category master; mandatory human review."
            ),
            confidence=confidence,
            threshold=threshold,
            policy_note=policy.policy_note,
        )
    if not policy.auto_resolution_allowed:
        return GateDecision(
            outcome=GateOutcome.HUMAN_QUEUE,
            rule_applied=AutoResolutionNotAllowedError.rule,
            reason=(
                f"Category {policy.category_id} has auto_resolution_allowed="
                f"False in the category master."
            ),
            confidence=confidence,
            threshold=threshold,
            policy_note=policy.policy_note,
        )
    if confidence < threshold:
        return GateDecision(
            outcome=GateOutcome.HUMAN_QUEUE,
            rule_applied=ConfidenceBelowThresholdError.rule,
            reason=(
                f"Decision confidence {confidence:.2f} is below the configured "
                f"threshold {threshold:.2f}."
            ),
            confidence=confidence,
            threshold=threshold,
            policy_note=policy.policy_note,
        )
    return GateDecision(
        outcome=GateOutcome.AUTO_RESOLVE,
        rule_applied="CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT",
        reason=(
            f"Category {policy.category_id} is not sensitive, permits automated "
            f"resolution, and confidence {confidence:.2f} meets the threshold "
            f"{threshold:.2f}."
        ),
        confidence=confidence,
        threshold=threshold,
        policy_note=policy.policy_note,
    )


#: A neighbour below this similarity is too weak to justify withholding
#: automation. Configurable, because it trades throughput against caution.
PRECAUTIONARY_SIMILARITY = float(
    os.environ.get("PRECAUTIONARY_SENSITIVE_SIMILARITY", "0.30")
)


def apply_precautionary_hold(
    gate: GateDecision,
    *,
    sensitive_neighbours: Sequence[Mapping[str, Any]] = (),
    wording_matches: Sequence[Mapping[str, Any]] = (),
) -> GateDecision:
    """Withhold automation when either signal says the case may be sensitive.

    Two independent signals, because each fails differently:

    * retrieved neighbours filed under a sensitive category — strong with
      semantic embeddings, blind with the lexical fallback;
    * the complaint using distinctive wording from a sensitive category in
      the master — needs no embedding at all.

    Only ever downgrades AUTO_RESOLVE to HUMAN_QUEUE. A case already heading
    for human review is returned untouched, and nothing here can promote a
    case into automation, which is what keeps rule 1 intact.
    """
    if gate.outcome is not GateOutcome.AUTO_RESOLVE:
        return gate

    strong = [
        neighbour
        for neighbour in sensitive_neighbours
        if float(neighbour.get("similarity") or 0) >= PRECAUTIONARY_SIMILARITY
    ]

    reason: str | None = None
    if strong:
        best = max(strong, key=lambda n: float(n.get("similarity") or 0))
        reason = (
            f"The chosen category permits automation, but {len(strong)} similar "
            f"past case(s) are filed under sensitive categories (closest "
            f"{best.get('category_id')} at similarity "
            f"{float(best.get('similarity') or 0):.2f})."
        )
    elif wording_matches:
        best = wording_matches[0]
        terms = ", ".join(best.get("terms", []))
        reason = (
            f"The chosen category permits automation, but the complaint uses "
            f"wording specific to sensitive category {best.get('category_id')} "
            f"({terms})."
        )

    if reason is None:
        return gate

    return GateDecision(
        outcome=GateOutcome.HUMAN_QUEUE,
        rule_applied=PrecautionarySensitiveError.rule,
        reason=(
            f"{reason} The category may be wrong, so this is held for human "
            f"review rather than resolved automatically."
        ),
        confidence=gate.confidence,
        threshold=gate.threshold,
        policy_note=gate.policy_note,
    )


def authorize_status_change(
    *,
    actor: Actor,
    policy: PolicySnapshot,
    new_status: str,
    confidence: float | None = None,
    threshold: float | None = None,
) -> str:
    """Authorise a status transition, or raise.

    This is the single enforcement point for rules 1 and 2. Every write path
    (API endpoint, Action Agent, scheduled job, seed script) calls it, and it
    reads the *live* policy snapshot rather than any flag stored on the
    ticket, so swapping the category CSV re-gates cases already in flight.

    Returns the name of the rule that permitted the change, for the audit log.
    """
    status = (new_status or "").strip()
    if not status:
        raise PolicyViolation("status must not be empty", rule="STATUS_REQUIRED")

    if actor is not Actor.AI_SYSTEM:
        # Human officers retain full authority, including rejection and
        # closing sensitive cases. Their action is logged under their own ID.
        return "HUMAN_ACTOR_AUTHORISED"

    if status not in AI_ALLOWED_STATUSES:
        raise AutoRejectionError(
            f"actor {actor.value} may not set status {status!r}; automated "
            f"actors are restricted to {sorted(AI_ALLOWED_STATUSES)}. Rejecting "
            f"a grievance or determining liability is reserved for a human officer."
        )

    if status in CLOSING_STATUSES:
        if policy.sensitive:
            raise SensitiveAutoCloseError(
                f"category {policy.category_id} is flagged sensitive in the "
                f"category master and can never be closed by {actor.value}; "
                f"route to human review."
            )
        if not policy.auto_resolution_allowed:
            raise AutoResolutionNotAllowedError(
                f"category {policy.category_id} has auto_resolution_allowed=False; "
                f"{actor.value} may not set status {status!r}."
            )
        if threshold is not None:
            if confidence is None:
                raise ConfidenceBelowThresholdError(
                    f"{actor.value} must supply a confidence value to close a case."
                )
            if confidence < threshold:
                raise ConfidenceBelowThresholdError(
                    f"confidence {confidence:.2f} is below the configured "
                    f"threshold {threshold:.2f}; route to human review."
                )
        return "AI_CLOSURE_PERMITTED_BY_CATEGORY_POLICY"

    return "AI_NON_TERMINAL_STATUS_PERMITTED"


# --------------------------------------------------------------------------
# Rule 3: identity masking
# --------------------------------------------------------------------------


def mask_identity(
    payload: Mapping[str, Any], *, policy: PolicySnapshot, audience: Audience
) -> dict[str, Any]:
    """Return a copy of payload with identifying fields masked when required.

    Applied to department-facing API responses, webhook bodies and notification
    payloads through one code path, so there is a single place to test. The
    complainant reading their own case is never masked.
    """
    out = dict(payload)
    should_mask = policy.identity_hiding and audience in MASKED_AUDIENCES
    out["identity_masked"] = should_mask
    if not should_mask:
        return out
    for key in list(out):
        if key in IDENTITY_FIELDS and out[key] not in (None, ""):
            out[key] = MASK_PLACEHOLDER
    return out


# --------------------------------------------------------------------------
# Rule 4: audit entries
# --------------------------------------------------------------------------


def build_audit_entry(
    *,
    actor: Actor,
    action: str,
    target: str,
    reasoning: str,
    actor_id: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    rule_applied: str | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Build one audit-log entry, rejecting incomplete AI entries.

    An AI action must carry model, confidence, timestamp and reasoning. A human
    action must carry the officer ID instead; a human is not required to supply
    a model or a confidence score.
    """
    ts = timestamp or datetime.now(timezone.utc)
    if not action or not target or not reasoning:
        raise IncompleteAuditError("action, target and reasoning are required")

    if actor is Actor.AI_SYSTEM:
        if not model:
            raise IncompleteAuditError("AI actions must record the model used")
        if confidence is None:
            raise IncompleteAuditError("AI actions must record a confidence value")
    elif not actor_id:
        raise IncompleteAuditError(
            f"{actor.value} actions must record the acting officer or citizen ID"
        )

    return {
        "actor": actor.value,
        "actor_id": actor_id,
        "model": model,
        "confidence": confidence,
        "timestamp": ts,
        "reasoning": reasoning,
        "action": action,
        "target": target,
        "rule_applied": rule_applied,
    }


def build_refusal_audit_entry(
    *,
    actor: Actor,
    attempted_action: str,
    target: str,
    violation: PolicyViolation,
    actor_id: str | None = None,
    model: str | None = None,
    confidence: float | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Record an action a guard refused to perform.

    A blocked attempt is still an AI action and belongs in the audit trail:
    the trail should show that the system was asked to auto-close a sensitive
    case and declined, not merely that nothing happened.

    This builder does not demand model or confidence. Nothing was done, so
    there is no decision to attribute, and inventing a confidence value to
    satisfy a validator would put a fabricated number in the audit log.
    """
    return {
        "actor": actor.value,
        "actor_id": actor_id,
        "model": model,
        "confidence": confidence,
        "timestamp": timestamp or datetime.now(timezone.utc),
        "reasoning": f"REFUSED: {violation}",
        "action": f"REFUSED_{attempted_action}",
        "target": target,
        "rule_applied": violation.rule,
    }


# --------------------------------------------------------------------------
# Rule 5: decision evidence
# --------------------------------------------------------------------------


def build_decision_record(
    *,
    grievance_ref: str,
    gate: GateDecision,
    retrieved_case_ids: Sequence[str],
    model: str,
    rationale: str,
) -> dict[str, Any]:
    """Build the stored decision, refusing to record one without its evidence.

    retrieved_case_ids may legitimately be empty (no similar case was found),
    but it must be supplied explicitly, so a decision can never be stored
    without a record of what evidence was or was not available.
    """
    if retrieved_case_ids is None:
        raise IncompleteDecisionError(
            "retrieved_case_ids must be supplied (an empty list is valid)"
        )
    if not gate.rule_applied:
        raise IncompleteDecisionError("the applied policy rule must be recorded")
    if not rationale:
        raise IncompleteDecisionError("a decision rationale must be recorded")
    return {
        "grievance_ref": grievance_ref,
        "gate_outcome": gate.outcome.value,
        "policy_rule_applied": gate.rule_applied,
        "policy_reason": gate.reason,
        "confidence": gate.confidence,
        "confidence_threshold": gate.threshold,
        "retrieved_case_ids": list(retrieved_case_ids),
        "model": model,
        "rationale": rationale,
    }


# --------------------------------------------------------------------------
# Rule 6: labelling AI output
# --------------------------------------------------------------------------


def label_ai_output(value: Any, *, kind: str, model: str) -> dict[str, Any]:
    """Wrap any AI-produced value so it can never be rendered as a fact.

    Summaries, risk scores, sentiment and image assessments all pass through
    here; the UI reads the label rather than deciding for itself.
    """
    return {
        "kind": kind,
        "value": value,
        "label": AI_LABEL,
        "verified": False,
        "model": model,
    }


# --------------------------------------------------------------------------
# Rule 7: priority
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PriorityInputs:
    """The only permitted inputs to priority.

    There is deliberately no field for duplicate or submission count: rule 7
    forbids volume from driving priority, and leaving the field out makes that
    violation impossible to express rather than merely discouraged.

    severity             - how harmful the reported condition is (0..1)
    urgency              - how time-critical it is (0..1)
    affected_population  - estimated number of PEOPLE affected per the
                           complaint content, normalised to 0..1. This is not
                           how many tickets were filed.
    """

    severity: float
    urgency: float
    affected_population: float

    def __post_init__(self) -> None:
        for name in ("severity", "urgency", "affected_population"):
            value = getattr(self, name)
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be within 0..1, got {value!r}")


#: Weights for the three permitted signals. Tunable without touching logic.
PRIORITY_WEIGHTS: dict[str, float] = {
    "severity": 0.45,
    "urgency": 0.35,
    "affected_population": 0.20,
}

#: Score thresholds for each band, evaluated high to low.
PRIORITY_BANDS: tuple[tuple[float, str], ...] = (
    (0.80, "CRITICAL"),
    (0.55, "HIGH"),
    (0.30, "MEDIUM"),
    (0.00, "LOW"),
)


def compute_priority(
    inputs: PriorityInputs, *, category_default: str | None = None
) -> tuple[str, float]:
    """Compute priority from severity, urgency and affected population.

    The category master's default_priority acts as a floor: a category the
    policy already considers CRITICAL is never demoted by a low score, but a
    severe individual case can be escalated above its category default.

    Returns (priority, score) so the score can be shown in the explainability
    panel alongside the band.
    """
    score = (
        PRIORITY_WEIGHTS["severity"] * inputs.severity
        + PRIORITY_WEIGHTS["urgency"] * inputs.urgency
        + PRIORITY_WEIGHTS["affected_population"] * inputs.affected_population
    )
    computed = next(band for floor, band in PRIORITY_BANDS if score >= floor)
    if category_default and category_default in PRIORITY_ORDER:
        if PRIORITY_ORDER.index(category_default) > PRIORITY_ORDER.index(computed):
            return category_default, score
    return computed, score


# --------------------------------------------------------------------------
# Rule 8: mock destinations only
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Destination:
    """A resolved outbound destination, before anything is sent."""

    channel: str
    address: str
    is_real_contact: bool
    department_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


#: Domains reserved by RFC 2606 / RFC 6761 for documentation and testing.
MOCK_EMAIL_SUFFIXES: tuple[str, ...] = (
    ".invalid",
    ".example",
    ".test",
    ".localhost",
    "@example.com",
    "@example.org",
    "@example.net",
)


def assert_mock_destination(destination: Destination) -> None:
    """Refuse to dispatch anything to a destination that is not a placeholder.

    Two independent checks: the directory's own is_real_contact flag, and the
    shape of the address itself, so a CSV that forgets the flag still cannot
    cause real mail to be addressed.
    """
    if destination.is_real_contact:
        raise RealContactError(
            f"department {destination.department_id or destination.address!r} is "
            f"marked is_real_contact=True; outbound delivery is disabled. All "
            f"demo contacts must be placeholders."
        )
    address = (destination.address or "").strip().lower()
    if not address:
        raise RealContactError("destination address is empty")
    if "@" in address and not any(address.endswith(s) or s in address for s in MOCK_EMAIL_SUFFIXES):
        raise RealContactError(
            f"refusing to address {destination.address!r}: it is not a reserved "
            f"placeholder domain. This system never contacts a real address."
        )
