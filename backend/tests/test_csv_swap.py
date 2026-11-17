"""Proof that behaviour follows the CSVs, not the code.

The success criterion is: swapping in a new category CSV changes routing with
no code change. These tests load the supplied master, assert one behaviour,
then point DATA_DIR at a fixture directory whose CSV disagrees on every
relevant field and assert the behaviour changed accordingly.

The fixture deliberately includes a category that is identity-hiding WITHOUT
being sensitive, because the supplied file never separates those flags.
"""
from __future__ import annotations

import pytest

from app.loaders import reload_reference_data
from app.policy.guards import (
    Actor,
    Audience,
    GateOutcome,
    MASK_PLACEHOLDER,
    SensitiveAutoCloseError,
    authorize_status_change,
    evaluate_policy_gate,
    mask_identity,
)
from app.policy.store import UnknownCategoryError, get_policy
from app.services.grievance_service import create_grievance


def test_supplied_master_routes_c001_to_its_own_department(loaded_session):
    policy = get_policy(loaded_session, "C001")
    assert policy.responsible_department_id == "D001"
    assert policy.sla_days == 5
    assert policy.sensitive is False
    assert policy.auto_resolution_allowed is True


def test_swapped_master_changes_routing_sla_and_policy(session, swapped_settings):
    """Same category id, different CSV, different behaviour. No code change."""
    reload_reference_data(session, swapped_settings, include_history=False)

    policy = get_policy(session, "C001")
    assert policy.responsible_department_id == "D003"  # was D001
    assert policy.sla_days == 1  # was 5
    assert policy.default_priority == "CRITICAL"  # was HIGH
    assert policy.sensitive is True  # was False

    # And the gate now sends it to human review.
    gate = evaluate_policy_gate(policy, confidence=0.99, threshold=0.75)
    assert gate.outcome is GateOutcome.HUMAN_QUEUE

    # And an automated closure that previously would have been permitted is
    # now refused, with no code having changed.
    with pytest.raises(SensitiveAutoCloseError):
        authorize_status_change(
            actor=Actor.AI_SYSTEM,
            policy=policy,
            new_status="Closed",
            confidence=0.99,
            threshold=0.75,
        )


def test_new_grievance_is_routed_by_the_swapped_csv(session, swapped_settings):
    reload_reference_data(session, swapped_settings, include_history=False)
    grievance = create_grievance(
        session,
        complaint_text="Pothole on the main road.",
        category_id="C001",
        taluka="Nanded",
    )
    session.commit()
    assert grievance.department_id == "D003"
    assert grievance.assignee == "Sanitation Department - Night Shift (Demo)"
    assert grievance.sla_days == 1
    assert grievance.priority == "CRITICAL"


def test_identity_hiding_without_sensitive_is_honoured(session, swapped_settings):
    """The decoupled case the supplied CSV never exercises."""
    reload_reference_data(session, swapped_settings, include_history=False)
    policy = get_policy(session, "C002")

    assert policy.sensitive is False
    assert policy.identity_hiding is True

    # Identity is masked for the department...
    masked = mask_identity(
        {"citizen_name": "Test Person"}, policy=policy, audience=Audience.DEPARTMENT
    )
    assert masked["citizen_name"] == MASK_PLACEHOLDER

    # ...but automation remains permitted, because it is not sensitive.
    gate = evaluate_policy_gate(policy, confidence=0.9, threshold=0.75)
    assert gate.outcome is GateOutcome.AUTO_RESOLVE
    assert authorize_status_change(
        actor=Actor.AI_SYSTEM,
        policy=policy,
        new_status="Closed",
        confidence=0.9,
        threshold=0.75,
    )


def test_a_category_invented_by_the_new_csv_is_usable(session, swapped_settings):
    """A category id absent from the supplied master works with no code edit."""
    reload_reference_data(session, swapped_settings, include_history=False)
    policy = get_policy(session, "C900")
    assert policy.responsible_department_id == "D002"
    assert policy.sla_days == 2


def test_a_category_removed_by_the_new_csv_stops_resolving(session, swapped_settings):
    """A removed category is refused rather than silently defaulted.

    Defaulting an unknown category would mean guessing whether it is
    sensitive, which is exactly the guess that must never be made.
    """
    reload_reference_data(session, swapped_settings, include_history=False)
    with pytest.raises(UnknownCategoryError):
        get_policy(session, "C018")


def test_jurisdiction_talukas_come_from_the_csv(session, swapped_settings):
    from app.policy.store import get_department

    reload_reference_data(session, swapped_settings, include_history=False)
    dept = get_department(session, "D001")
    assert dept is not None
    assert dept.jurisdiction_type == "Taluka-specific"
    assert dept.jurisdiction_talukas == ["Nanded", "Mukhed"]


def test_supplied_directory_parses_all_sixteen_talukas(loaded_session):
    from app.policy.store import get_department

    dept = get_department(loaded_session, "D001")
    assert dept is not None
    assert len(dept.jurisdiction_talukas) == 16
    assert "Nanded" in dept.jurisdiction_talukas
    assert "Mukhed" in dept.jurisdiction_talukas
