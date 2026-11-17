"""Pipeline tests.

They run with no API key, so the offline provider is used and the suite is
hermetic. What is asserted is the wiring and the policy behaviour, not the
model's classification quality.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agents.graph import build_graph, run_pipeline
from app.agents.decision_agent import normalise_population
from app.agents.policy_agent import run_policy
from app.agents.state import PipelineState
from app.llm.provider import Completion, StubProvider
from app.models import AuditLog, CategoryMaster, Decision, Grievance, Notification
from app.policy.guards import GateOutcome, SensitiveAutoCloseError
from app.rag.embeddings import embed_texts
from app.rag.retrieval import KEYWORD_OVERLAP, retrieve_similar


def _category(session, *, sensitive: bool):
    return session.scalars(
        select(CategoryMaster)
        .where(CategoryMaster.sensitive == sensitive)
        .order_by(CategoryMaster.category_id)
    ).first()


class ScriptedProvider:
    """A provider that returns a fixed draft, to test the graph, not the model."""

    def __init__(self, category_id: str | None, confidence: float) -> None:
        self.name = "scripted-test-provider"
        self._category_id = category_id
        self._confidence = confidence

    def complete_json(self, *, system, user, schema_hint, context) -> Completion:
        return Completion(
            text=json.dumps(
                {
                    "category_id": self._category_id,
                    "description": user,
                    "urgency": "HIGH",
                    "severity": 0.5,
                    "urgency_score": 0.5,
                    "affected_population_estimate": 10,
                    "missing_details": [],
                    "confidence": self._confidence,
                    "rationale": "scripted",
                }
            ),
            model=self.name,
            confidence=self._confidence,
        )


class TestGraphWiring:
    def test_graph_compiles_with_all_six_nodes(self, loaded_session):
        compiled = build_graph(loaded_session)
        nodes = set(compiled.get_graph().nodes)
        for expected in ("intake", "confirm", "retrieval", "policy", "decision", "action"):
            assert expected in nodes

    def test_a_run_produces_every_stage(self, loaded_session):
        state = run_pipeline(
            loaded_session,
            raw_text="Streetlight not working near the main road in Mukhed.",
            taluka="Mukhed",
        )
        assert state["draft"]
        assert "method" in state["evidence"]
        assert state["gate"]["rule_applied"]
        assert state["decision"]["policy_rule_applied"]
        assert state["actions"]


class TestSensitiveCaseThroughThePipeline:
    def test_sensitive_case_is_queued_not_resolved(self, loaded_session):
        category = _category(loaded_session, sensitive=True)
        state = run_pipeline(
            loaded_session,
            raw_text="A confidential concern that needs review.",
            taluka="Nanded",
            provider=ScriptedProvider(category.category_id, 0.99),
        )
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value
        assert state["gate"]["rule_applied"] == SensitiveAutoCloseError.rule

        grievance = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == state["grievance_ref"])
        )
        assert grievance.status == "In Progress"
        assert grievance.status != "Resolved"

    def test_high_confidence_does_not_unlock_automation(self, loaded_session):
        category = _category(loaded_session, sensitive=True)
        state = run_pipeline(
            loaded_session,
            raw_text="A confidential concern.",
            provider=ScriptedProvider(category.category_id, 1.0),
        )
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value

    def test_identity_is_masked_in_the_webhook_payload(self, loaded_session):
        category = loaded_session.scalars(
            select(CategoryMaster).where(CategoryMaster.identity_hiding.is_(True))
        ).first()
        state = run_pipeline(
            loaded_session,
            raw_text="A confidential concern.",
            citizen_name="Test Person",
            citizen_phone="0000000000",
            provider=ScriptedProvider(category.category_id, 0.9),
        )
        webhook = loaded_session.scalar(
            select(Notification).where(Notification.channel == "webhook")
        )
        assert webhook is not None
        assert webhook.identity_masked is True
        assert webhook.payload["citizen_name"] != "Test Person"
        assert state["grievance_ref"]


class TestRoutineCase:
    def test_routine_case_is_auto_resolved(self, loaded_session):
        category = loaded_session.scalars(
            select(CategoryMaster).where(
                CategoryMaster.sensitive.is_(False),
                CategoryMaster.auto_resolution_allowed.is_(True),
            )
        ).first()
        state = run_pipeline(
            loaded_session,
            raw_text="A routine civic issue.",
            taluka="Nanded",
            provider=ScriptedProvider(category.category_id, 0.95),
        )
        assert state["gate"]["outcome"] == GateOutcome.AUTO_RESOLVE.value
        grievance = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == state["grievance_ref"])
        )
        assert grievance.status == "Resolved"

    def test_routing_comes_from_the_master(self, loaded_session):
        category = loaded_session.scalars(
            select(CategoryMaster).where(CategoryMaster.sensitive.is_(False))
        ).first()
        state = run_pipeline(
            loaded_session,
            raw_text="A routine civic issue.",
            provider=ScriptedProvider(category.category_id, 0.95),
        )
        assert state["decision"]["department_id"] == category.responsible_department_id
        assert state["decision"]["assignee"] == category.default_assignee


class TestLowConfidenceAndUnknownCategory:
    def test_low_confidence_goes_to_the_human_queue(self, loaded_session):
        category = _category(loaded_session, sensitive=False)
        state = run_pipeline(
            loaded_session,
            raw_text="Something ambiguous.",
            provider=ScriptedProvider(category.category_id, 0.05),
        )
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value

    def test_unclassifiable_complaint_creates_no_ticket(self, loaded_session):
        state = run_pipeline(
            loaded_session,
            raw_text="zzzz",
            provider=ScriptedProvider(None, 0.0),
        )
        assert state["grievance_ref"] is None
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value
        assert state["gate"]["rule_applied"] == "CATEGORY_UNDETERMINED_REQUIRES_HUMAN_REVIEW"

    def test_a_category_absent_from_the_master_is_not_guessed(self, loaded_session):
        state: PipelineState = {
            "draft": {"category_id": "C999-NOT-IN-MASTER"},
            "intake_confidence": 0.99,
        }
        run_policy(loaded_session, state)
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value
        assert state["gate"]["sensitive"] is None


class TestRetrievalIsEvidenceOnly:
    def test_retrieval_cannot_change_the_gate(self, loaded_session):
        """Past auto-closures of similar cases do not unlock a sensitive one."""
        category = _category(loaded_session, sensitive=True)
        state: PipelineState = {
            "draft": {"category_id": category.category_id},
            "intake_confidence": 0.99,
            "retrieved_case_ids": ["GRV-00002"],  # an AI-auto-closed past case
            "evidence": {"cases": [{"grievance_id": "GRV-00002", "status": "Resolved"}]},
        }
        run_policy(loaded_session, state)
        assert state["gate"]["outcome"] == GateOutcome.HUMAN_QUEUE.value

    def test_retrieval_result_is_labelled_evidence_only(self, loaded_session):
        result = retrieve_similar(loaded_session, "water pipeline leakage", k=3)
        assert result.as_dict()["evidence_only"] is True
        assert result.rationale

    def test_keyword_fallback_when_nothing_is_embedded(self, loaded_session):
        result = retrieve_similar(loaded_session, "water pipeline leakage", k=3)
        assert result.method == KEYWORD_OVERLAP

    def test_semantic_retrieval_once_embeddings_exist(self, loaded_session):
        from app.models import GrievanceHistory

        rows = list(
            loaded_session.scalars(select(GrievanceHistory).limit(50))
        )
        for row, vector in zip(rows, embed_texts([r.complaint_text for r in rows])):
            row.embedding = vector
        loaded_session.flush()

        result = retrieve_similar(loaded_session, "water is leaking from a pipeline", k=3)
        assert result.method != KEYWORD_OVERLAP
        assert result.cases
        assert all(c.similarity > 0 for c in result.cases), (
            "zero-similarity results would be fabricated evidence"
        )


class TestDecisionRecordAndAudit:
    def test_decision_row_stores_its_evidence(self, loaded_session):
        category = _category(loaded_session, sensitive=False)
        state = run_pipeline(
            loaded_session,
            raw_text="A routine civic issue.",
            provider=ScriptedProvider(category.category_id, 0.95),
        )
        decision = loaded_session.scalar(select(Decision).order_by(Decision.id.desc()))
        assert decision is not None
        assert decision.confidence == 0.95
        assert decision.policy_rule_applied
        assert decision.rationale
        assert decision.retrieved_case_ids == state["retrieved_case_ids"]

    def test_every_ai_action_is_audited_with_model_and_confidence(self, loaded_session):
        category = _category(loaded_session, sensitive=False)
        state = run_pipeline(
            loaded_session,
            raw_text="A routine civic issue.",
            provider=ScriptedProvider(category.category_id, 0.95),
        )
        rows = loaded_session.scalars(
            select(AuditLog).where(AuditLog.target == state["grievance_ref"])
        ).all()
        ai_rows = [r for r in rows if r.actor == "AI_SYSTEM"]
        assert ai_rows
        for row in ai_rows:
            assert row.model
            assert row.confidence is not None
            assert row.reasoning
            assert row.timestamp


class TestPriorityFromPipeline:
    def test_population_normalisation_is_monotonic_and_bounded(self):
        assert normalise_population(0) == 0.0
        assert normalise_population(None) == 0.0
        assert normalise_population("not a number") == 0.0
        assert 0 < normalise_population(10) < normalise_population(500) <= 1.0
        assert normalise_population(10_000_000) == 1.0


class TestOfflineProvider:
    def test_stub_picks_a_category_from_the_loaded_master(self, loaded_session):
        from app.agents.intake import category_catalogue

        provider = StubProvider()
        result = provider.complete_json(
            system="",
            user="There is a pothole and damaged road here.",
            schema_hint="",
            context={"categories": category_catalogue(loaded_session)},
        ).as_json()
        chosen = loaded_session.get(CategoryMaster, result["category_id"])
        assert chosen is not None

    def test_stub_reports_zero_confidence_when_nothing_matches(self, loaded_session):
        from app.agents.intake import category_catalogue

        result = StubProvider().complete_json(
            system="",
            user="qqqq zzzz",
            schema_hint="",
            context={"categories": category_catalogue(loaded_session)},
        ).as_json()
        assert result["category_id"] is None
        assert result["confidence"] == 0.0


class TestTracingIsOptional:
    def test_pipeline_runs_with_tracing_disabled(self, loaded_session):
        from app.observability.trace import tracing_enabled

        assert tracing_enabled() is False
        state = run_pipeline(loaded_session, raw_text="A routine civic issue.")
        assert state["gate"]
