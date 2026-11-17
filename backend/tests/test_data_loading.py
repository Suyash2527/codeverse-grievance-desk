"""Loader and parser tests, including the data quirks found during review."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.csvdata import (
    DataFormatError,
    parse_bool,
    parse_category_master,
    parse_jurisdiction_talukas,
)
from app.loaders import reload_reference_data
from app.models import CategoryMaster, DepartmentDirectory, GrievanceHistory


class TestStrictBooleans:
    def test_accepts_the_dataset_spelling(self):
        assert parse_bool("True", field="sensitive", row_id="C001") is True
        assert parse_bool("False", field="sensitive", row_id="C001") is False

    @pytest.mark.parametrize("value", ["TRUE", "true", "1", "", "yes", "Y", " True"])
    def test_rejects_everything_else(self, value):
        """A lenient parser would turn these into False and un-gate a rule."""
        with pytest.raises(DataFormatError):
            parse_bool(value, field="sensitive", row_id="C001")


class TestJurisdictionParsing:
    def test_strips_the_prose_prefix(self):
        parsed = parse_jurisdiction_talukas(
            "All 16 sample talukas: Nanded; Ardhapur; Mukhed"
        )
        assert parsed == ["Nanded", "Ardhapur", "Mukhed"]

    def test_accepts_a_bare_list(self):
        assert parse_jurisdiction_talukas("Nanded; Mukhed") == ["Nanded", "Mukhed"]

    def test_empty_mapping_yields_no_talukas(self):
        assert parse_jurisdiction_talukas("") == []


class TestSuppliedFiles:
    def test_bom_does_not_corrupt_the_first_column(self, real_settings_fixture):
        """All three files are UTF-8 with BOM; the join key must survive it."""
        rows = parse_category_master(real_settings_fixture.category_master_csv)
        assert rows[0].category_id == "C001"

    def test_row_counts_match_the_documented_dataset(self, loaded_session):
        assert loaded_session.scalar(select(func.count()).select_from(CategoryMaster)) == 30
        assert (
            loaded_session.scalar(select(func.count()).select_from(DepartmentDirectory)) == 20
        )
        assert loaded_session.scalar(select(func.count()).select_from(GrievanceHistory)) == 800

    def test_every_category_joins_to_a_known_department(self, loaded_session):
        dept_ids = set(loaded_session.scalars(select(DepartmentDirectory.department_id)))
        cat_depts = set(
            loaded_session.scalars(select(CategoryMaster.responsible_department_id))
        )
        assert cat_depts <= dept_ids

    def test_every_history_row_joins_to_a_known_category(self, loaded_session):
        cat_ids = set(loaded_session.scalars(select(CategoryMaster.category_id)))
        hist_cats = set(
            loaded_session.scalars(select(GrievanceHistory.category_id).distinct())
        )
        assert hist_cats <= cat_ids

    def test_orphan_department_is_reported_not_fatal(self, session, real_settings_fixture):
        """D009 is in the directory but no category routes to it."""
        report = reload_reference_data(session, real_settings_fixture)
        assert report.categories == 30
        assert any("no category routes to it" in w for w in report.warnings)

    def test_resolution_days_are_precomputed(self, loaded_session):
        row = loaded_session.scalar(
            select(GrievanceHistory).where(GrievanceHistory.resolution_date.isnot(None))
        )
        assert row is not None
        assert row.resolution_days == (row.resolution_date - row.submission_date).days

    def test_unresolved_rows_have_no_duration(self, loaded_session):
        count = loaded_session.scalar(
            select(func.count())
            .select_from(GrievanceHistory)
            .where(
                GrievanceHistory.resolution_date.is_(None),
                GrievanceHistory.resolution_days.isnot(None),
            )
        )
        assert count == 0

    def test_dates_are_parsed_as_dates(self, loaded_session):
        row = loaded_session.get(GrievanceHistory, "GRV-00001")
        assert isinstance(row.submission_date, date)

    def test_reload_replaces_rather_than_appends(self, session, real_settings_fixture):
        reload_reference_data(session, real_settings_fixture)
        reload_reference_data(session, real_settings_fixture)
        assert session.scalar(select(func.count()).select_from(CategoryMaster)) == 30


class TestNoHardcodedPolicy:
    def test_flags_are_read_from_the_file_not_a_literal_list(self, loaded_session):
        """Whatever the file says is sensitive, is sensitive.

        Asserted as a property of the loaded data rather than against a fixed
        list of category ids, so the test survives a CSV swap.
        """
        sensitive = set(
            loaded_session.scalars(
                select(CategoryMaster.category_id).where(CategoryMaster.sensitive.is_(True))
            )
        )
        assert sensitive, "the supplied master must contain at least one sensitive category"
        for cid in sensitive:
            row = loaded_session.get(CategoryMaster, cid)
            assert row.auto_resolution_allowed is False, (
                f"{cid} is sensitive but permits auto resolution; the guards "
                f"would still block closure, but the data is contradictory"
            )
