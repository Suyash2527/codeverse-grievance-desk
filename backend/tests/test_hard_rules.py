"""One test group per hard rule.

These are the pass/fail criteria, so they are tested against the guard layer
directly (deterministic, no LLM involved) and, where the rule describes an
endpoint behaviour, through the API as well.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import AuditLog, CategoryMaster
from app.policy.guards import (
    AI_LABEL,
    Actor,
    Audience,
    AutoRejectionError,
    AutoResolutionNotAllowedError,
    ConfidenceBelowThresholdError,
    Destination,
    GateOutcome,
    IncompleteAuditError,
    IncompleteDecisionError,
    MASK_PLACEHOLDER,
    PolicySnapshot,
    PriorityInputs,
    RealContactError,
    SensitiveAutoCloseError,
    assert_mock_destination,
    authorize_status_change,
    build_audit_entry,
    build_decision_record,
    compute_priority,
    evaluate_policy_gate,
    label_ai_output,
    mask_identity,
)
from app.policy.store import get_policy
from app.services.grievance_service import create_grievance, update_status


def _first_category(session, *, sensitive: bool, identity_hiding: bool | None = None):
    """Pick a category from the loaded master by its flags.

    Deliberately not hardcoded to a category id: the tests must keep working
    when the CSV is replaced.
    """
    stmt = select(CategoryMaster).where(CategoryMaster.sensitive == sensitive)
    if identity_hiding is not None:
        stmt = stmt.where(CategoryMaster.identity_hiding == identity_hiding)
    row = session.scalars(stmt.order_by(CategoryMaster.category_id)).first()
    assert row is not None, "the loaded master has no category matching the test"
    return row


# --------------------------------------------------------------------------
# Rule 1: a Sensitive case is never auto-closed
# --------------------------------------------------------------------------


class TestRule1SensitiveNeverAutoClosed:
    def test_guard_blocks_ai_close_of_sensitive_case(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=True).category_id
        )
        with pytest.raises(SensitiveAutoCloseError):
            authorize_status_change(
                actor=Actor.AI_SYSTEM,
                policy=policy,
                new_status="Closed",
                confidence=0.99,
                threshold=0.75,
            )

    def test_maximum_confidence_does_not_override_the_flag(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=True).category_id
        )
        with pytest.raises(SensitiveAutoCloseError):
            authorize_status_change(
                actor=Actor.AI_SYSTEM,
                policy=policy,
                new_status="Resolved",
                confidence=1.0,
                threshold=0.0,
            )

    def test_gate_routes_sensitive_to_human_queue(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=True).category_id
        )
        gate = evaluate_policy_gate(policy, confidence=0.99, threshold=0.75)
        assert gate.outcome is GateOutcome.HUMAN_QUEUE
        assert gate.rule_applied == SensitiveAutoCloseError.rule

    def test_human_officer_may_still_close_a_sensitive_case(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=True).category_id
        )
        assert authorize_status_change(
            actor=Actor.OFFICER, policy=policy, new_status="Closed"
        )

    def test_service_layer_refuses_and_leaves_status_untouched(self, loaded_session):
        category = _first_category(loaded_session, sensitive=True)
        grievance = create_grievance(
            loaded_session,
            complaint_text="Test sensitive case.",
            category_id=category.category_id,
            taluka="Nanded",
        )
        loaded_session.commit()
        with pytest.raises(SensitiveAutoCloseError):
            update_status(
                loaded_session,
                grievance=grievance,
                new_status="Closed",
                actor=Actor.AI_SYSTEM,
                model="test-model",
                confidence=0.99,
                reasoning="attempting an automated closure",
            )
        assert grievance.status == "Submitted"

    def test_api_rejects_ai_close_of_sensitive_case(self, client, loaded_session):
        category = _first_category(loaded_session, sensitive=True)
        created = client.post(
            "/api/grievances",
            json={
                "complaint_text": "Sensitive matter requiring confidential review.",
                "category_id": category.category_id,
                "taluka": "Nanded",
            },
        )
        assert created.status_code == 201
        reference = created.json()["reference_no"]

        response = client.patch(
            f"/api/grievances/{reference}/status",
            json={
                "status": "Closed",
                "actor": "AI_SYSTEM",
                "model": "test-model",
                "confidence": 0.99,
                "reasoning": "agent requested automated closure",
            },
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["rule"] == SensitiveAutoCloseError.rule

        still_open = client.get(f"/api/grievances/{reference}").json()
        assert still_open["status"] == "Submitted"

    def test_the_refusal_itself_is_audited(self, client, loaded_session):
        """A blocked attempt must be visible in the audit trail, not silent."""
        category = _first_category(loaded_session, sensitive=True)
        reference = client.post(
            "/api/grievances",
            json={"complaint_text": "Sensitive matter.", "category_id": category.category_id},
        ).json()["reference_no"]

        client.patch(
            f"/api/grievances/{reference}/status",
            json={
                "status": "Closed",
                "actor": "AI_SYSTEM",
                "model": "test-model",
                "confidence": 0.99,
                "reasoning": "agent requested automated closure",
            },
        )

        logs = client.get("/api/audit-logs", params={"target": reference}).json()
        refusals = [r for r in logs if r["action"].startswith("REFUSED_")]
        assert len(refusals) == 1
        assert refusals[0]["rule_applied"] == SensitiveAutoCloseError.rule
        assert refusals[0]["actor"] == "AI_SYSTEM"
        assert "REFUSED" in refusals[0]["reasoning"]

    def test_api_allows_officer_to_close_the_same_case(self, client, loaded_session):
        category = _first_category(loaded_session, sensitive=True)
        reference = client.post(
            "/api/grievances",
            json={
                "complaint_text": "Sensitive matter requiring confidential review.",
                "category_id": category.category_id,
            },
        ).json()["reference_no"]

        response = client.patch(
            f"/api/grievances/{reference}/status",
            json={
                "status": "Closed",
                "actor": "OFFICER",
                "actor_id": "officer-demo-01",
                "reasoning": "reviewed and closed by the duty officer",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "Closed"


# --------------------------------------------------------------------------
# Rule 2: the AI never auto-rejects and never rules on liability
# --------------------------------------------------------------------------


class TestRule2NoAutoRejection:
    @pytest.mark.parametrize(
        "status",
        ["Rejected", "Dismissed", "Invalid", "Not Admissible", "Liable", "Closed - Rejected"],
    )
    def test_ai_cannot_set_a_rejection_status(self, loaded_session, status):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        with pytest.raises(AutoRejectionError):
            authorize_status_change(
                actor=Actor.AI_SYSTEM, policy=policy, new_status=status
            )

    def test_allow_list_is_what_blocks_them(self, loaded_session):
        """Any status outside the allow-list is refused, not just known words."""
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        with pytest.raises(AutoRejectionError):
            authorize_status_change(
                actor=Actor.AI_SYSTEM,
                policy=policy,
                new_status="Some Status A Future CSV Invents",
            )

    def test_api_rejects_ai_rejection_attempt(self, client, loaded_session):
        category = _first_category(loaded_session, sensitive=False)
        reference = client.post(
            "/api/grievances",
            json={"complaint_text": "Routine issue.", "category_id": category.category_id},
        ).json()["reference_no"]
        response = client.patch(
            f"/api/grievances/{reference}/status",
            json={
                "status": "Rejected",
                "actor": "AI_SYSTEM",
                "model": "test-model",
                "confidence": 0.99,
                "reasoning": "agent judged the complaint invalid",
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["rule"] == AutoRejectionError.rule


# --------------------------------------------------------------------------
# Rule 3: identity hiding
# --------------------------------------------------------------------------


class TestRule3IdentityHiding:
    def test_identity_is_masked_for_department_audience(self, loaded_session):
        policy = get_policy(
            loaded_session,
            _first_category(loaded_session, sensitive=True, identity_hiding=True).category_id,
        )
        masked = mask_identity(
            {"citizen_name": "Test Person", "citizen_phone": "0000000000", "status": "Submitted"},
            policy=policy,
            audience=Audience.DEPARTMENT,
        )
        assert masked["citizen_name"] == MASK_PLACEHOLDER
        assert masked["citizen_phone"] == MASK_PLACEHOLDER
        assert masked["identity_masked"] is True
        assert masked["status"] == "Submitted"

    @pytest.mark.parametrize(
        "audience", [Audience.DEPARTMENT, Audience.WEBHOOK, Audience.NOTIFICATION]
    )
    def test_masking_covers_webhooks_and_notifications(self, loaded_session, audience):
        policy = get_policy(
            loaded_session,
            _first_category(loaded_session, sensitive=True, identity_hiding=True).category_id,
        )
        masked = mask_identity(
            {"citizen_name": "Test Person"}, policy=policy, audience=audience
        )
        assert masked["citizen_name"] == MASK_PLACEHOLDER

    def test_citizen_sees_their_own_details(self, loaded_session):
        policy = get_policy(
            loaded_session,
            _first_category(loaded_session, sensitive=True, identity_hiding=True).category_id,
        )
        own = mask_identity(
            {"citizen_name": "Test Person"},
            policy=policy,
            audience=Audience.CITIZEN_SELF,
        )
        assert own["citizen_name"] == "Test Person"
        assert own["identity_masked"] is False

    def test_non_identity_hiding_category_is_not_masked(self, loaded_session):
        policy = get_policy(
            loaded_session,
            _first_category(loaded_session, sensitive=False, identity_hiding=False).category_id,
        )
        payload = mask_identity(
            {"citizen_name": "Test Person"}, policy=policy, audience=Audience.DEPARTMENT
        )
        assert payload["citizen_name"] == "Test Person"

    def test_masking_follows_identity_flag_independently_of_sensitive(self):
        """A category may be identity-hiding without being sensitive.

        The supplied CSV happens to set both flags together; this asserts the
        guards read them independently so a replacement CSV behaves correctly.
        """
        policy = PolicySnapshot(
            category_id="CTEST",
            sensitive=False,
            identity_hiding=True,
            auto_resolution_allowed=True,
            sla_days=3,
            default_priority="LOW",
            responsible_department_id="D001",
            default_assignee="Demo",
        )
        masked = mask_identity(
            {"citizen_name": "Test Person"}, policy=policy, audience=Audience.DEPARTMENT
        )
        assert masked["citizen_name"] == MASK_PLACEHOLDER
        # ... and automation is still permitted for it.
        assert (
            evaluate_policy_gate(policy, confidence=0.9, threshold=0.75).outcome
            is GateOutcome.AUTO_RESOLVE
        )

    def test_department_view_of_a_live_case_is_masked(self, client, loaded_session):
        category = _first_category(loaded_session, sensitive=True, identity_hiding=True)
        reference = client.post(
            "/api/grievances",
            json={
                "complaint_text": "Confidential concern.",
                "category_id": category.category_id,
                "citizen_name": "Test Person",
                "citizen_phone": "0000000000",
            },
        ).json()["reference_no"]

        dept_view = client.get(
            f"/api/grievances/{reference}", params={"audience": "DEPARTMENT"}
        ).json()
        assert dept_view["citizen_name"] == MASK_PLACEHOLDER
        assert dept_view["identity_masked"] is True


# --------------------------------------------------------------------------
# Rule 4: every AI action is audited
# --------------------------------------------------------------------------


class TestRule4AuditLogging:
    def test_ai_entry_requires_model_and_confidence(self):
        with pytest.raises(IncompleteAuditError):
            build_audit_entry(
                actor=Actor.AI_SYSTEM,
                action="UPDATE_STATUS",
                target="GRV-TEST",
                reasoning="because",
                confidence=0.9,
            )
        with pytest.raises(IncompleteAuditError):
            build_audit_entry(
                actor=Actor.AI_SYSTEM,
                action="UPDATE_STATUS",
                target="GRV-TEST",
                reasoning="because",
                model="test-model",
            )

    def test_ai_entry_has_the_required_shape(self):
        entry = build_audit_entry(
            actor=Actor.AI_SYSTEM,
            action="UPDATE_STATUS",
            target="GRV-TEST",
            reasoning="routine civic request matching category policy",
            model="test-model",
            confidence=0.88,
        )
        assert entry["actor"] == "AI_SYSTEM"
        assert entry["model"] == "test-model"
        assert entry["confidence"] == 0.88
        assert isinstance(entry["timestamp"], datetime)
        assert entry["reasoning"]

    def test_human_entry_requires_an_officer_id(self):
        with pytest.raises(IncompleteAuditError):
            build_audit_entry(
                actor=Actor.OFFICER,
                action="UPDATE_STATUS",
                target="GRV-TEST",
                reasoning="reviewed",
            )
        entry = build_audit_entry(
            actor=Actor.OFFICER,
            actor_id="officer-demo-01",
            action="UPDATE_STATUS",
            target="GRV-TEST",
            reasoning="reviewed",
        )
        assert entry["actor_id"] == "officer-demo-01"

    def test_status_change_writes_an_audit_row(self, loaded_session):
        category = _first_category(loaded_session, sensitive=False)
        grievance = create_grievance(
            loaded_session,
            complaint_text="Routine issue.",
            category_id=category.category_id,
        )
        update_status(
            loaded_session,
            grievance=grievance,
            new_status="In Progress",
            actor=Actor.AI_SYSTEM,
            model="test-model",
            confidence=0.9,
            reasoning="assigned to the responsible department",
        )
        loaded_session.commit()
        rows = loaded_session.scalars(
            select(AuditLog).where(AuditLog.target == grievance.reference_no)
        ).all()
        actions = {r.action for r in rows}
        assert {"CREATE_GRIEVANCE", "UPDATE_STATUS"} <= actions
        ai_row = next(r for r in rows if r.actor == "AI_SYSTEM")
        assert ai_row.model == "test-model"
        assert ai_row.confidence == 0.9
        assert ai_row.reasoning
        assert ai_row.rule_applied


# --------------------------------------------------------------------------
# Rule 5: decisions store their evidence
# --------------------------------------------------------------------------


class TestRule5DecisionEvidence:
    def test_decision_record_carries_confidence_cases_and_rule(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        gate = evaluate_policy_gate(policy, confidence=0.91, threshold=0.75)
        record = build_decision_record(
            grievance_ref="GRV-TEST",
            gate=gate,
            retrieved_case_ids=["GRV-00001", "GRV-00002"],
            model="test-model",
            rationale="two similar past cases were resolved by the same department",
        )
        assert record["confidence"] == 0.91
        assert record["confidence_threshold"] == 0.75
        assert record["retrieved_case_ids"] == ["GRV-00001", "GRV-00002"]
        assert record["policy_rule_applied"] == gate.rule_applied
        assert record["policy_reason"]

    def test_decision_without_a_rationale_is_refused(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        gate = evaluate_policy_gate(policy, confidence=0.91, threshold=0.75)
        with pytest.raises(IncompleteDecisionError):
            build_decision_record(
                grievance_ref="GRV-TEST",
                gate=gate,
                retrieved_case_ids=[],
                model="test-model",
                rationale="",
            )

    def test_empty_evidence_is_allowed_but_explicit(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        gate = evaluate_policy_gate(policy, confidence=0.91, threshold=0.75)
        record = build_decision_record(
            grievance_ref="GRV-TEST",
            gate=gate,
            retrieved_case_ids=[],
            model="test-model",
            rationale="no sufficiently similar past case was found",
        )
        assert record["retrieved_case_ids"] == []

    def test_low_confidence_routes_to_human_queue(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        gate = evaluate_policy_gate(policy, confidence=0.10, threshold=0.75)
        assert gate.outcome is GateOutcome.HUMAN_QUEUE
        assert gate.rule_applied == ConfidenceBelowThresholdError.rule

    def test_ai_cannot_close_below_threshold(self, loaded_session):
        policy = get_policy(
            loaded_session, _first_category(loaded_session, sensitive=False).category_id
        )
        with pytest.raises(ConfidenceBelowThresholdError):
            authorize_status_change(
                actor=Actor.AI_SYSTEM,
                policy=policy,
                new_status="Closed",
                confidence=0.10,
                threshold=0.75,
            )


# --------------------------------------------------------------------------
# Rule 6: AI output is labelled
# --------------------------------------------------------------------------


class TestRule6AIOutputLabelled:
    @pytest.mark.parametrize("kind", ["summary", "risk_score", "image_assessment", "sentiment"])
    def test_every_ai_output_is_labelled_and_unverified(self, kind):
        labelled = label_ai_output("some value", kind=kind, model="test-model")
        assert labelled["label"] == AI_LABEL
        assert labelled["verified"] is False
        assert labelled["kind"] == kind
        assert labelled["model"] == "test-model"


# --------------------------------------------------------------------------
# Rule 7: priority composition
# --------------------------------------------------------------------------


class TestRule7Priority:
    def test_priority_inputs_reject_out_of_range_values(self):
        with pytest.raises(ValueError):
            PriorityInputs(severity=1.5, urgency=0.5, affected_population=0.5)

    def test_priority_has_no_submission_count_input(self):
        """Volume cannot influence priority because there is no field for it."""
        assert set(PriorityInputs.__dataclass_fields__) == {
            "severity",
            "urgency",
            "affected_population",
        }
        with pytest.raises(TypeError):
            PriorityInputs(  # type: ignore[call-arg]
                severity=0.5,
                urgency=0.5,
                affected_population=0.5,
                submission_count=40,
            )

    def test_duplicate_volume_does_not_change_priority(self):
        """Two identical cases rank the same however many reports exist."""
        inputs = PriorityInputs(severity=0.6, urgency=0.6, affected_population=0.3)
        first, _ = compute_priority(inputs, category_default="MEDIUM")
        second, _ = compute_priority(inputs, category_default="MEDIUM")
        assert first == second

    def test_higher_severity_never_lowers_priority(self):
        low = compute_priority(PriorityInputs(0.2, 0.2, 0.2))[1]
        high = compute_priority(PriorityInputs(0.9, 0.2, 0.2))[1]
        assert high > low

    def test_affected_population_raises_the_score(self):
        few = compute_priority(PriorityInputs(0.5, 0.5, 0.1))[1]
        many = compute_priority(PriorityInputs(0.5, 0.5, 0.9))[1]
        assert many > few

    def test_category_default_acts_as_a_floor(self):
        band, _ = compute_priority(
            PriorityInputs(0.05, 0.05, 0.05), category_default="CRITICAL"
        )
        assert band == "CRITICAL"

    def test_a_severe_case_can_escalate_above_its_category_default(self):
        band, _ = compute_priority(
            PriorityInputs(0.95, 0.95, 0.9), category_default="LOW"
        )
        assert band == "CRITICAL"


# --------------------------------------------------------------------------
# Rule 8: mock destinations only
# --------------------------------------------------------------------------


class TestRule8MockContactsOnly:
    def test_every_supplied_department_contact_is_a_placeholder(self, loaded_session):
        from app.policy.store import list_departments

        for dept in list_departments(loaded_session):
            assert_mock_destination(
                Destination(
                    channel="email",
                    address=dept.contact_email_demo,
                    is_real_contact=dept.is_real_contact,
                    department_id=dept.department_id,
                )
            )

    def test_a_real_contact_flag_blocks_delivery(self):
        with pytest.raises(RealContactError):
            assert_mock_destination(
                Destination(
                    channel="email",
                    address="someone@example.invalid",
                    is_real_contact=True,
                    department_id="D001",
                )
            )

    def test_a_real_looking_address_blocks_delivery_even_if_flag_is_false(self):
        with pytest.raises(RealContactError):
            assert_mock_destination(
                Destination(
                    channel="email",
                    address="grievances@nanded.gov.in",
                    is_real_contact=False,
                    department_id="D001",
                )
            )

    def test_empty_address_is_refused(self):
        with pytest.raises(RealContactError):
            assert_mock_destination(
                Destination(channel="email", address="", is_real_contact=False)
            )


# --------------------------------------------------------------------------
# Cross-cutting: categories that forbid automation for a non-sensitive reason
# --------------------------------------------------------------------------


def test_auto_resolution_disallowed_blocks_closure(loaded_session):
    policy = PolicySnapshot(
        category_id="CTEST",
        sensitive=False,
        identity_hiding=False,
        auto_resolution_allowed=False,
        sla_days=3,
        default_priority="LOW",
        responsible_department_id="D001",
        default_assignee="Demo",
    )
    with pytest.raises(AutoResolutionNotAllowedError):
        authorize_status_change(
            actor=Actor.AI_SYSTEM,
            policy=policy,
            new_status="Closed",
            confidence=1.0,
            threshold=0.75,
        )


def test_supplied_dataset_honours_rule_1_itself(loaded_session):
    """No sensitive case in the supplied history was ever AI auto-closed."""
    from app.models import GrievanceHistory

    offenders = loaded_session.scalars(
        select(GrievanceHistory).where(
            GrievanceHistory.sensitive.is_(True),
            GrievanceHistory.ai_auto_closed.is_(True),
        )
    ).all()
    assert offenders == []
