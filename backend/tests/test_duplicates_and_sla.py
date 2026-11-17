"""Duplicate grouping and SLA escalation.

The two rules under test here are easy to violate by accident:

* grouping must never merge, close or hide a grievance, and
* an escalation alert must arrive BEFORE the deadline, including when the
  history is too thin to predict anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.agents.graph import run_pipeline
from app.models import AuditLog, CategoryMaster, Grievance, GrievanceHistory, SlaAlert
from app.services import duplicates, sla
from tests.test_pipeline import ScriptedProvider

BURST_PIPE = [
    "The water pipeline near the market road has burst and water is flowing down the street.",
    "A pipeline has burst on market road, there is water everywhere since morning.",
    "Water leaking heavily from the broken pipeline at market road. Please send someone.",
]


def _routine_category(session):
    return session.scalars(
        select(CategoryMaster).where(
            CategoryMaster.sensitive.is_(False),
            CategoryMaster.auto_resolution_allowed.is_(True),
        )
    ).first()


def _file(session, text: str, *, category, taluka="Mukhed", locality="Mukhed Town"):
    return run_pipeline(
        session,
        raw_text=text,
        taluka=taluka,
        locality=locality,
        provider=ScriptedProvider(category.category_id, 0.4),  # stays open
    )


def _file_group(session, *, locality="Mukhed Town"):
    category = _routine_category(session)
    return [
        _file(session, text, category=category, locality=locality)
        for text in BURST_PIPE
    ]


class TestDuplicateGrouping:
    def test_similar_reports_in_one_place_are_grouped(self, loaded_session):
        _file_group(loaded_session)
        result = duplicates.group_duplicates(loaded_session)
        assert result["incidents"], "three near-identical reports should group"
        assert len(result["incidents"][0]["members"]) == 3

    def test_nothing_is_merged_closed_or_deleted(self, loaded_session):
        states = _file_group(loaded_session)
        references = [s["grievance_ref"] for s in states]
        before = {
            g.reference_no: (g.status, g.sla_due_at)
            for g in loaded_session.scalars(select(Grievance))
        }

        duplicates.group_duplicates(loaded_session)

        rows = list(loaded_session.scalars(select(Grievance)))
        assert len(rows) == 3, "no grievance may be removed by grouping"
        for row in rows:
            assert row.reference_no in references
            assert row.status == before[row.reference_no][0], "status must not change"
            assert row.sla_due_at == before[row.reference_no][1], "deadline must not move"
            assert row.incident_id is not None

    def test_every_member_keeps_its_own_reference(self, loaded_session):
        states = _file_group(loaded_session)
        duplicates.group_duplicates(loaded_session)
        incidents = duplicates.list_incidents(loaded_session)
        members = {m["reference_no"] for m in incidents[0]["members"]}
        assert members == {s["grievance_ref"] for s in states}
        assert len(members) == 3

    def test_grouping_is_audited_per_grievance(self, loaded_session):
        states = _file_group(loaded_session)
        duplicates.group_duplicates(loaded_session)
        for state in states:
            entries = loaded_session.scalars(
                select(AuditLog).where(
                    AuditLog.target == state["grievance_ref"],
                    AuditLog.action == "LINK_TO_INCIDENT",
                )
            ).all()
            assert entries
            assert entries[0].rule_applied == "DUPLICATES_GROUPED_NEVER_MERGED"
            assert "keeps its own reference number" in entries[0].reasoning

    def test_different_localities_are_not_grouped(self, loaded_session):
        category = _routine_category(loaded_session)
        _file(loaded_session, BURST_PIPE[0], category=category, locality="Mukhed Town")
        _file(loaded_session, BURST_PIPE[1], category=category, locality="Far Village")
        result = duplicates.group_duplicates(loaded_session)
        assert result["incidents"] == []

    def test_reports_outside_the_window_are_not_grouped(self, loaded_session):
        states = _file_group(loaded_session)
        old = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        old.created_at = datetime.now(timezone.utc) - timedelta(
            days=duplicates.WINDOW_DAYS + 5
        )
        loaded_session.flush()
        result = duplicates.group_duplicates(loaded_session)
        grouped = {r for inc in result["incidents"] for r in inc["members"]}
        assert old.reference_no not in grouped

    def test_grouping_twice_does_not_duplicate_incidents(self, loaded_session):
        _file_group(loaded_session)
        duplicates.group_duplicates(loaded_session)
        second = duplicates.group_duplicates(loaded_session)
        assert second["incidents"] == []
        assert len(duplicates.list_incidents(loaded_session)) == 1

    def test_officer_confirmation_is_recorded(self, loaded_session):
        _file_group(loaded_session)
        duplicates.group_duplicates(loaded_session)
        incident = duplicates.list_incidents(loaded_session)[0]
        duplicates.confirm_incident(
            loaded_session,
            incident_id=incident["id"],
            officer_id="officer-demo-01",
            note="Same burst pipe.",
        )
        assert duplicates.list_incidents(loaded_session)[0]["confirmed_by"] == (
            "officer-demo-01"
        )

    def test_threshold_differs_by_embedding_space(self):
        """One fixed cosine threshold cannot serve both embedding methods."""
        assert (
            duplicates.LEXICAL_THRESHOLD_DEFAULT
            < duplicates.SEMANTIC_THRESHOLD_DEFAULT
        )


class TestSlaStatistics:
    def test_stats_report_their_basis_and_sample_size(self, loaded_session):
        category = _routine_category(loaded_session)
        stats = sla.duration_stats(
            loaded_session,
            category_id=category.category_id,
            department_id=category.responsible_department_id,
            sla_days=category.sla_days,
        )
        assert stats.basis == sla.BASIS_CATEGORY_DEPARTMENT
        assert stats.sample_size >= sla.MIN_SAMPLES
        assert stats.p80_days is not None
        assert stats.usable is True

    def test_thin_history_refuses_to_estimate(self, loaded_session):
        """A category with no closed history must not produce a prediction."""
        loaded_session.execute(
            GrievanceHistory.__table__.delete()
        )
        loaded_session.flush()
        category = _routine_category(loaded_session)
        stats = sla.duration_stats(
            loaded_session,
            category_id=category.category_id,
            department_id=category.responsible_department_id,
            sla_days=category.sla_days,
        )
        assert stats.usable is False
        assert stats.basis == sla.BASIS_NONE
        assert stats.sample_size == 0

    def test_breach_rate_is_measured_not_assumed(self, loaded_session):
        category = _routine_category(loaded_session)
        stats = sla.duration_stats(
            loaded_session,
            category_id=category.category_id,
            department_id=category.responsible_department_id,
            sla_days=category.sla_days,
        )
        assert stats.breach_rate is not None
        assert 0.0 <= stats.breach_rate <= 1.0


class TestSlaEscalation:
    def test_alert_is_raised_before_the_deadline(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        due = case.sla_due_at.replace(tzinfo=timezone.utc)
        scan_at = due - timedelta(hours=2)

        result = sla.scan(loaded_session, now=scan_at)
        assert result["alerts_raised"] >= 1

        alert = loaded_session.scalar(
            select(SlaAlert).where(SlaAlert.grievance_id == case.id)
        )
        assert alert is not None
        raised = alert.raised_at.replace(tzinfo=timezone.utc)
        assert raised < due, "the alert must arrive before the deadline"
        assert alert.risk in sla.ESCALATING_RISKS

    def test_alert_carries_its_evidence(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        scan_at = case.sla_due_at.replace(tzinfo=timezone.utc) - timedelta(hours=2)
        sla.scan(loaded_session, now=scan_at)
        alert = loaded_session.scalar(
            select(SlaAlert).where(SlaAlert.grievance_id == case.id)
        )
        assert alert.sample_size > 0
        assert alert.sla_days == case.sla_days
        assert "comparable" in alert.reason or "deadline" in alert.reason

    def test_an_on_track_case_raises_nothing(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        # Scan immediately after filing: the whole window is still ahead.
        scan_at = case.created_at.replace(tzinfo=timezone.utc) + timedelta(minutes=1)
        result = sla.scan(loaded_session, now=scan_at, raise_alerts=False)
        risks = {a["risk"] for a in result["assessments"]}
        assert risks <= {
            sla.RISK_ON_TRACK,
            sla.RISK_BREACH_LIKELY,
            sla.RISK_UNKNOWN,
        }

    def test_scanning_twice_does_not_duplicate_alerts(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        scan_at = case.sla_due_at.replace(tzinfo=timezone.utc) - timedelta(hours=2)
        first = sla.scan(loaded_session, now=scan_at)
        second = sla.scan(loaded_session, now=scan_at)
        assert first["alerts_raised"] > 0
        assert second["alerts_raised"] == 0

    def test_overdue_case_is_marked_overdue(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        past_due = case.sla_due_at.replace(tzinfo=timezone.utc) + timedelta(days=1)
        assessment = sla.assess(loaded_session, case, now=past_due)
        assert assessment.risk == sla.RISK_OVERDUE
        assert assessment.hours_remaining < 0

    def test_closed_cases_are_not_scanned(self, loaded_session):
        states = _file_group(loaded_session)
        for state in states:
            row = loaded_session.scalar(
                select(Grievance).where(Grievance.reference_no == state["grievance_ref"])
            )
            row.status = "Closed"
        loaded_session.flush()
        result = sla.scan(loaded_session)
        assert result["open_cases"] == 0
        assert result["alerts_raised"] == 0

    def test_naive_and_aware_timestamps_are_both_accepted(self, loaded_session):
        """SQLite hands back naive datetimes; the arithmetic must not shift."""
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        naive = case.sla_due_at.replace(tzinfo=None) - timedelta(hours=3)
        aware = naive.replace(tzinfo=timezone.utc)
        assert (
            sla.assess(loaded_session, case, now=naive).hours_remaining
            == pytest.approx(sla.assess(loaded_session, case, now=aware).hours_remaining)
        )

    def test_escalation_is_audited_as_an_ai_action(self, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        scan_at = case.sla_due_at.replace(tzinfo=timezone.utc) - timedelta(hours=2)
        sla.scan(loaded_session, now=scan_at)
        entry = loaded_session.scalar(
            select(AuditLog).where(
                AuditLog.target == case.reference_no,
                AuditLog.action == "RAISE_SLA_ALERT",
            )
        )
        assert entry is not None
        assert entry.actor == "AI_SYSTEM"
        assert entry.model == "sla-statistics"
        assert entry.confidence is not None


class TestOperationsApi:
    def test_sla_scan_endpoint_accepts_an_injected_now(self, client, loaded_session):
        states = _file_group(loaded_session)
        case = loaded_session.scalar(
            select(Grievance).where(Grievance.reference_no == states[0]["grievance_ref"])
        )
        scan_at = (
            case.sla_due_at.replace(tzinfo=timezone.utc) - timedelta(hours=2)
        ).isoformat()
        body = client.post("/api/jobs/sla-scan", params={"now": scan_at}).json()
        assert body["open_cases"] == 3
        assert body["alerts_raised"] >= 1

    def test_sla_scan_rejects_a_bad_timestamp(self, client, loaded_session):
        assert client.post("/api/jobs/sla-scan", params={"now": "yesterday"}).status_code == 422

    def test_incident_endpoints(self, client, loaded_session):
        _file_group(loaded_session)
        grouped = client.post("/api/incidents/group").json()
        assert grouped["incidents"]

        incidents = client.get("/api/incidents").json()
        assert incidents[0]["member_count"] == 3
        assert "keeps its own reference number" in incidents[0]["note"]

        confirmed = client.post(
            f"/api/incidents/{incidents[0]['id']}/confirm",
            json={"officer_id": "officer-demo-01", "note": "Same burst pipe."},
        )
        assert confirmed.status_code == 200

    def test_forecast_endpoint_exposes_the_evidence(self, client, loaded_session):
        states = _file_group(loaded_session)
        body = client.get(f"/api/sla/forecast/{states[0]['grievance_ref']}").json()
        assert body["stats"]["sample_size"] >= 0
        assert body["stats"]["min_samples"] == sla.MIN_SAMPLES
        assert body["reason"]
