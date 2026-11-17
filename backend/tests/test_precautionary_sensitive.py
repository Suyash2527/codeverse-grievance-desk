"""The second line of defence for rule 1.

The sensitive guard trusts the category. These tests cover what happens when
the category is wrong in the dangerous direction — a sparking live wire filed
as footpath damage — where the guard alone would let automation through.

The design rule under test: evidence is used asymmetrically. It may make the
system more cautious and can never make it less.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.llm.provider import Completion
from app.loaders import reload_reference_data
from app.models import CategoryMaster, Grievance, GrievanceHistory
from app.policy.guards import (
    GateDecision,
    GateOutcome,
    PrecautionarySensitiveError,
    apply_precautionary_hold,
)
from app.policy.sensitive_signals import (
    distinctive_sensitive_terms,
    sensitive_wording_matches,
)
from app.rag.embeddings import embed_texts


class ConfidentlyWrong:
    """A model that is certain, and wrong in the direction that matters."""

    name = "confidently-wrong"

    def __init__(self, category_id: str) -> None:
        self.category_id = category_id

    def complete_json(self, *, system, user, schema_hint, context) -> Completion:
        return Completion(
            text=json.dumps(
                {
                    "category_id": self.category_id,
                    "description": user,
                    "urgency": "MEDIUM",
                    "severity": 0.5,
                    "urgency_score": 0.5,
                    "affected_population_estimate": 0,
                    "missing_details": [],
                    "confidence": 0.99,
                }
            ),
            model=self.name,
            confidence=0.99,
        )


def _embed_history(session) -> None:
    rows = list(session.scalars(select(GrievanceHistory)))
    for row, vector in zip(rows, embed_texts([r.complaint_text for r in rows])):
        row.embedding = vector
    session.flush()


class TestHoldIsOneDirectional:
    def test_it_never_promotes_a_queued_case(self):
        """Nothing in this path may unlock automation. Rule 1 depends on it."""
        queued = GateDecision(
            outcome=GateOutcome.HUMAN_QUEUE,
            rule_applied="RULE_1_SENSITIVE_NEVER_AUTO_CLOSED",
            reason="sensitive",
            confidence=0.99,
            threshold=0.75,
        )
        held = apply_precautionary_hold(
            queued,
            sensitive_neighbours=[{"category_id": "C018", "similarity": 0.99}],
            wording_matches=[{"category_id": "C018", "terms": ["child"]}],
        )
        assert held.outcome is GateOutcome.HUMAN_QUEUE
        assert held.rule_applied == "RULE_1_SENSITIVE_NEVER_AUTO_CLOSED"

    def test_a_clean_case_passes_through_untouched(self):
        clean = GateDecision(
            outcome=GateOutcome.AUTO_RESOLVE,
            rule_applied="CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT",
            reason="fine",
            confidence=0.9,
            threshold=0.75,
        )
        assert apply_precautionary_hold(clean) is clean

    def test_a_weak_neighbour_does_not_trigger_a_hold(self):
        clean = GateDecision(
            outcome=GateOutcome.AUTO_RESOLVE,
            rule_applied="CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT",
            reason="fine",
            confidence=0.9,
            threshold=0.75,
        )
        held = apply_precautionary_hold(
            clean, sensitive_neighbours=[{"category_id": "C018", "similarity": 0.05}]
        )
        assert held.outcome is GateOutcome.AUTO_RESOLVE

    def test_a_strong_neighbour_withholds_automation(self):
        clean = GateDecision(
            outcome=GateOutcome.AUTO_RESOLVE,
            rule_applied="CATEGORY_AUTO_RESOLUTION_ALLOWED_AND_CONFIDENT",
            reason="fine",
            confidence=0.99,
            threshold=0.75,
        )
        held = apply_precautionary_hold(
            clean, sensitive_neighbours=[{"category_id": "C018", "similarity": 0.8}]
        )
        assert held.outcome is GateOutcome.HUMAN_QUEUE
        assert held.rule_applied == PrecautionarySensitiveError.rule
        assert "C018" in held.reason


class TestDistinctiveWording:
    def test_terms_are_derived_from_the_loaded_master(self, loaded_session):
        terms = distinctive_sensitive_terms(loaded_session)
        sensitive_ids = set(
            loaded_session.scalars(
                select(CategoryMaster.category_id).where(
                    CategoryMaster.identity_hiding.is_(True)
                )
            )
        )
        assert set(terms) <= sensitive_ids
        assert terms, "the supplied master must yield some distinctive terms"

    def test_common_words_are_excluded(self, loaded_session):
        """"public" and "service" appear everywhere and must not fire."""
        all_terms = set().union(*distinctive_sensitive_terms(loaded_session).values())
        assert "public" not in all_terms
        assert "service" not in all_terms

    def test_wording_from_a_sensitive_category_is_detected(self, loaded_session):
        matches = sensitive_wording_matches(
            loaded_session, "a live wire is sparking over the footpath"
        )
        assert any(m["category_id"] == "C010" for m in matches)

    def test_routine_wording_matches_nothing(self, loaded_session):
        assert (
            sensitive_wording_matches(
                loaded_session, "pipeline leakage is wasting water near the road"
            )
            == []
        )

    def test_the_vocabulary_follows_a_swapped_csv(self, session, swapped_settings):
        """No keyword list is hardcoded; the terms come from the CSV."""
        reload_reference_data(session, swapped_settings, include_history=False)
        terms = distinctive_sensitive_terms(session)
        # In the fixture master, C001 (roads/potholes) is the sensitive one.
        assert "C001" in terms
        assert any("pothole" in term or "road" in term for term in terms["C001"])


class TestEndToEnd:
    def test_a_misclassified_live_wire_is_held(self, loaded_session):
        from app.agents.graph import run_pipeline

        _embed_history(loaded_session)
        state = run_pipeline(
            loaded_session,
            raw_text="A live wire is hanging low over the footpath and sparking.",
            taluka="Nanded",
            provider=ConfidentlyWrong("C002"),
        )
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value
        assert state["gate"]["rule_applied"] == PrecautionarySensitiveError.rule

        grievance = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == state["grievance_ref"])
        )
        assert grievance.status != "Resolved"

    def test_a_genuinely_routine_case_still_auto_resolves(self, loaded_session):
        """Caution must not swallow the routine path; scenario 1 depends on it."""
        from app.agents.graph import run_pipeline

        _embed_history(loaded_session)
        state = run_pipeline(
            loaded_session,
            raw_text="Pipeline leakage is wasting water near the market road.",
            taluka="Mukhed",
            provider=ConfidentlyWrong("C003"),
        )
        assert state["gate"]["outcome"] == GateOutcome.AUTO_RESOLVE.value

        grievance = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == state["grievance_ref"])
        )
        assert grievance.status == "Resolved"
