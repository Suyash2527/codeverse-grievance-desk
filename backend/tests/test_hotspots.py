"""Taluka hotspot analytics.

The aggregation itself is simple arithmetic; what needs testing is the
privacy contract, because this is the view most likely to end up on a screen
in a room full of people.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import CategoryMaster, GrievanceHistory
from app.services import hotspots
from app.services.hotspots import MIN_CELL_SIZE, SUPPRESSED


class TestAggregation:
    def test_every_known_taluka_appears(self, loaded_session):
        """A taluka with no complaints is a finding, not an omission."""
        result = hotspots.hotspots(loaded_session)
        assert len(result["talukas"]) == 16

    def test_counts_match_the_history(self, loaded_session):
        result = hotspots.hotspots(loaded_session)
        for row in result["talukas"]:
            expected = loaded_session.scalar(
                select(GrievanceHistory)
                .where(GrievanceHistory.broad_location_taluka == row["taluka"])
                .limit(1)
            )
            assert expected is not None or row["historical_total"] == 0
        total = sum(row["historical_total"] for row in result["talukas"])
        assert total == 800

    def test_district_breach_rate_matches_the_dataset(self, loaded_session):
        result = hotspots.hotspots(loaded_session)
        district = result["district"]
        assert district["historical_closed"] == 496
        assert district["historical_breach_rate"] == 0.653

    def test_breach_rate_is_none_without_closed_cases(self, loaded_session):
        loaded_session.execute(GrievanceHistory.__table__.delete())
        loaded_session.flush()
        result = hotspots.hotspots(loaded_session)
        assert all(row["historical_breach_rate"] is None for row in result["talukas"])


class TestPrivacyContract:
    def test_granularity_stops_at_taluka(self, loaded_session):
        """A locality plus a sensitive category can identify a household."""
        result = hotspots.hotspots(loaded_session)
        assert result["privacy"]["granularity"] == "taluka"
        serialised = repr(result)
        for row in result["talukas"]:
            assert "locality" not in row

        localities = set(
            loaded_session.scalars(
                select(GrievanceHistory.broad_location_locality).distinct()
            )
        )
        talukas = {row["taluka"] for row in result["talukas"]}
        leaked = {
            locality
            for locality in localities
            if locality not in talukas and locality in serialised
        }
        assert not leaked, f"locality names must not appear: {leaked}"

    def test_no_reference_numbers_are_exposed(self, loaded_session):
        result = hotspots.hotspots(loaded_session)
        assert "GRV-" not in repr(result)

    def test_small_sensitive_cells_are_suppressed(self, loaded_session):
        """One sensitive case in a small taluka is a disclosure, not a figure."""
        sensitive = loaded_session.scalars(
            select(CategoryMaster).where(CategoryMaster.identity_hiding.is_(True))
        ).first()

        # Leave a single sensitive case in one taluka and nothing else.
        loaded_session.execute(GrievanceHistory.__table__.delete())
        loaded_session.add(
            GrievanceHistory(
                grievance_id="GRV-TEST-1",
                complaint_text="A confidential concern.",
                category_id=sensitive.category_id,
                category=sensitive.category,
                subcategory=sensitive.subcategory,
                department_id=sensitive.responsible_department_id,
                broad_location_taluka="Mukhed",
                broad_location_locality="Mukhed Town",
                submission_date=__import__("datetime").date(2026, 1, 1),
                resolution_date=None,
                status="In Progress",
                resolution_text=None,
                citizen_feedback="Not yet provided",
                priority=sensitive.default_priority,
                sla_days=sensitive.sla_days,
                sensitive=True,
                identity_hiding=True,
                resolution_actor="NOT_RESOLVED",
                ai_auto_closed=False,
                data_origin="TEST",
            )
        )
        loaded_session.flush()

        result = hotspots.hotspots(loaded_session)
        mukhed = next(r for r in result["talukas"] if r["taluka"] == "Mukhed")

        assert mukhed["sensitive_cases"] == SUPPRESSED
        suppressed_entries = [c for c in mukhed["top_categories"] if c["suppressed"]]
        assert suppressed_entries, "the lone sensitive category must be withheld"
        assert suppressed_entries[0]["category_id"] == SUPPRESSED
        assert suppressed_entries[0]["count"] == SUPPRESSED
        assert sensitive.subcategory not in repr(mukhed)

    def test_large_sensitive_cells_are_reported(self, loaded_session):
        """Suppression protects individuals; it must not hide a real pattern."""
        result = hotspots.hotspots(loaded_session)
        reported = [
            row
            for row in result["talukas"]
            if isinstance(row["sensitive_cases"], int)
        ]
        assert reported, "with 127 sensitive cases, some talukas must report a figure"
        assert all(row["sensitive_cases"] >= MIN_CELL_SIZE for row in reported)

    def test_the_privacy_note_is_carried_to_the_client(self, loaded_session):
        result = hotspots.hotspots(loaded_session)
        assert result["privacy"]["min_cell_size"] == MIN_CELL_SIZE
        assert "taluka only" in result["privacy"]["note"]


class TestHotspotsApi:
    def test_endpoint_returns_the_aggregate(self, client, loaded_session):
        body = client.get("/api/analytics/hotspots").json()
        assert len(body["talukas"]) == 16
        assert body["privacy"]["granularity"] == "taluka"

    def test_endpoint_accepts_an_injected_now(self, client, loaded_session):
        body = client.get(
            "/api/analytics/hotspots", params={"now": "2026-11-20T00:00:00Z"}
        ).json()
        assert body["generated_at"].startswith("2026-11-20")

    def test_endpoint_rejects_a_bad_timestamp(self, client, loaded_session):
        assert (
            client.get(
                "/api/analytics/hotspots", params={"now": "tomorrow"}
            ).status_code
            == 422
        )
