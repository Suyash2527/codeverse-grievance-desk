"""Officer console API tests.

The queue is the screen an officer makes decisions from, so what it must
guarantee is tested here: identity masking follows the policy flag, the
ordering is by priority then deadline, AI output arrives labelled, and the
human actions are attributed to the officer rather than to the system.
"""
from __future__ import annotations

from sqlalchemy import select

from app.agents.graph import run_pipeline
from app.models import AuditLog, CategoryMaster
from app.policy.guards import AI_LABEL, MASK_PLACEHOLDER
from tests.test_pipeline import ScriptedProvider

OFFICER = "officer-demo-01"


def _seed(session, *, sensitive: bool, identity_hiding: bool | None = None, **kwargs):
    stmt = select(CategoryMaster).where(CategoryMaster.sensitive == sensitive)
    if identity_hiding is not None:
        stmt = stmt.where(CategoryMaster.identity_hiding == identity_hiding)
    category = session.scalars(stmt.order_by(CategoryMaster.category_id)).first()
    return run_pipeline(
        session,
        raw_text=kwargs.pop("text", "A reported civic issue needing attention."),
        taluka=kwargs.pop("taluka", "Nanded"),
        citizen_name=kwargs.pop("citizen_name", "Test Person"),
        citizen_phone="0000000000",
        provider=ScriptedProvider(category.category_id, kwargs.pop("confidence", 0.95)),
    )


class TestQueue:
    def test_queue_returns_seeded_cases(self, client, loaded_session):
        _seed(loaded_session, sensitive=False)
        body = client.get("/api/officer/queue").json()
        assert body["count"] == 1
        assert body["rows"][0]["reference_no"]

    def test_identity_is_masked_only_where_policy_requires(self, client, loaded_session):
        _seed(loaded_session, sensitive=True, identity_hiding=True)
        _seed(loaded_session, sensitive=False, identity_hiding=False)
        rows = client.get("/api/officer/queue").json()["rows"]

        hidden = [r for r in rows if r["policy"]["identity_hiding"]]
        visible = [r for r in rows if not r["policy"]["identity_hiding"]]
        assert hidden and visible

        for row in hidden:
            assert row["citizen_name"] == MASK_PLACEHOLDER
            assert row["identity_masked"] is True
        for row in visible:
            assert row["citizen_name"] == "Test Person"
            assert row["identity_masked"] is False

    def test_ai_summary_arrives_labelled(self, client, loaded_session):
        _seed(loaded_session, sensitive=False)
        row = client.get("/api/officer/queue").json()["rows"][0]
        assert row["ai_summary"]["label"] == AI_LABEL
        assert row["ai_summary"]["verified"] is False
        assert row["ai_sentiment"]["label"] == AI_LABEL

    def test_queue_carries_the_policy_rule_and_confidence(self, client, loaded_session):
        _seed(loaded_session, sensitive=True)
        row = client.get("/api/officer/queue").json()["rows"][0]
        assert row["gate"]["rule_applied"]
        assert row["gate"]["confidence"] is not None
        assert row["gate"]["confidence_threshold"] == 0.75

    def test_rows_are_ordered_by_priority_then_deadline(self, client, loaded_session):
        _seed(loaded_session, sensitive=True)  # CRITICAL by category default
        _seed(loaded_session, sensitive=False)
        rows = client.get("/api/officer/queue").json()["rows"]
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        ranks = [order[r["priority"]] for r in rows]
        assert ranks == sorted(ranks)

    def test_awaiting_review_filter_returns_only_queued_cases(self, client, loaded_session):
        _seed(loaded_session, sensitive=True)
        _seed(loaded_session, sensitive=False)
        rows = client.get(
            "/api/officer/queue", params={"awaiting_review": "true"}
        ).json()["rows"]
        assert rows
        assert all(r["gate"]["outcome"] == "HUMAN_QUEUE" for r in rows)

    def test_counts_summarise_the_queue(self, client, loaded_session):
        _seed(loaded_session, sensitive=True)
        body = client.get("/api/officer/queue").json()
        assert body["counts"]["sensitive"] == 1
        assert body["counts"]["awaiting_review"] == 1

    def test_queue_exposes_category_names_as_facts(self, client, loaded_session):
        """The UI headlines a case with these, so they must come from the master."""
        state = _seed(loaded_session, sensitive=False)
        row = client.get("/api/officer/queue").json()["rows"][0]
        category = loaded_session.get(CategoryMaster, row["category_id"])
        assert row["category"] == category.category
        assert row["subcategory"] == category.subcategory
        assert state["grievance_ref"] == row["reference_no"]


class TestApproveAndOverride:
    def test_officer_can_close_a_sensitive_case_the_ai_could_not(
        self, client, loaded_session
    ):
        state = _seed(loaded_session, sensitive=True)
        reference = state["grievance_ref"]

        # The pipeline already tried and was refused.
        refusals = loaded_session.scalars(
            select(AuditLog).where(
                AuditLog.target == reference, AuditLog.actor == "AI_SYSTEM"
            )
        ).all()
        assert any(r.action.startswith("REFUSED_") for r in refusals) or all(
            r.action != "UPDATE_STATUS_TO_CLOSED" for r in refusals
        )

        response = client.post(
            f"/api/officer/grievances/{reference}/approve",
            json={"officer_id": OFFICER, "note": "Reviewed in person.", "status": "Closed"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Closed"

    def test_approval_is_attributed_to_the_officer_not_the_system(
        self, client, loaded_session
    ):
        state = _seed(loaded_session, sensitive=False)
        reference = state["grievance_ref"]
        client.post(
            f"/api/officer/grievances/{reference}/approve",
            json={"officer_id": OFFICER, "note": "Agreed with the recommendation."},
        )
        entries = client.get("/api/audit-logs", params={"target": reference}).json()
        officer_entries = [e for e in entries if e["actor"] == "OFFICER"]
        assert officer_entries
        assert officer_entries[0]["actor_id"] == OFFICER
        assert officer_entries[0]["model"] is None

    def test_override_records_every_changed_field(self, client, loaded_session):
        state = _seed(loaded_session, sensitive=False)
        reference = state["grievance_ref"]
        response = client.post(
            f"/api/officer/grievances/{reference}/override",
            json={
                "officer_id": OFFICER,
                "note": "Wrong department for this locality.",
                "department_id": "D020",
                "priority": "LOW",
            },
        )
        assert response.status_code == 200
        assert response.json()["department_id"] == "D020"
        assert response.json()["priority"] == "LOW"

        entries = client.get("/api/audit-logs", params={"target": reference}).json()
        override = next(e for e in entries if e["action"] == "OVERRIDE_AI_DECISION")
        assert override["actor_id"] == OFFICER
        assert "department" in override["reasoning"]
        assert "priority" in override["reasoning"]
        assert override["rule_applied"] == "HUMAN_OVERRIDE"

    def test_an_override_that_changes_nothing_is_rejected(self, client, loaded_session):
        state = _seed(loaded_session, sensitive=False)
        response = client.post(
            f"/api/officer/grievances/{state['grievance_ref']}/override",
            json={"officer_id": OFFICER, "note": "No change."},
        )
        assert response.status_code == 422

    def test_unknown_reference_is_a_404(self, client, loaded_session):
        assert client.get("/api/officer/grievances/GRV-NOPE").status_code == 404
