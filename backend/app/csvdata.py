"""Strict parsers for the three supplied CSV files.

Design rules enforced here:

* Nothing about categories, SLAs, flags, departments, talukas or contacts is
  hardcoded. Every value is read from the CSV at runtime, so replacing a CSV
  changes behaviour with no code edit.
* Parsing is pure: these functions return dataclasses and never touch a
  database, so the policy tests run without Postgres.
* Booleans are strict. The supplied files use Python-style ``True``/``False``.
  Anything else raises, because a silently-misparsed ``sensitive`` flag would
  make a Sensitive category auto-closable.
* All three files are UTF-8 **with BOM**; they must be opened as ``utf-8-sig``
  or the first header becomes a BOM-prefixed name and every join key breaks.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ENCODING = "utf-8-sig"

TRUE_LITERALS = {"True"}
FALSE_LITERALS = {"False"}


class DataFormatError(ValueError):
    """Raised when a supplied CSV does not match its documented contract."""


def parse_bool(value: str, *, field: str, row_id: str) -> bool:
    """Parse the Python-style booleans used by the dataset, strictly.

    Lenient parsing is deliberately avoided: "TRUE", "1" or "" raise rather
    than defaulting to False, because these flags gate the never-auto-close
    and identity-masking rules.
    """
    if value in TRUE_LITERALS:
        return True
    if value in FALSE_LITERALS:
        return False
    raise DataFormatError(
        f"{field}={value!r} in row {row_id!r} is not a recognised boolean; "
        f"expected one of {sorted(TRUE_LITERALS | FALSE_LITERALS)}"
    )


def parse_int(value: str, *, field: str, row_id: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DataFormatError(
            f"{field}={value!r} in row {row_id!r} is not an integer"
        ) from exc


def parse_jurisdiction_talukas(mapping: str) -> list[str]:
    """Split jurisdiction_mapping into a list of taluka names.

    The supplied form is a single quoted cell such as::

        All 16 sample talukas: Nanded; Ardhapur; ...; Mukhed

    The prose prefix before the colon is dropped; the remainder is a
    semicolon-separated list. A cell with no colon is treated as a bare list,
    so a replacement CSV may supply "Nanded; Mukhed" directly.
    """
    if not mapping or not mapping.strip():
        return []
    _, sep, tail = mapping.partition(":")
    body = tail if sep else mapping
    return [part.strip() for part in body.split(";") if part.strip()]


@dataclass(frozen=True)
class CategoryRow:
    """One row of grievance_category_master.csv, the policy source of truth."""

    category_id: str
    category: str
    subcategory: str
    responsible_department_id: str
    responsible_department: str
    default_assignee: str
    sla_days: int
    sensitive: bool
    identity_hiding: bool
    default_priority: str
    auto_resolution_allowed: bool
    policy_note: str


@dataclass(frozen=True)
class DepartmentRow:
    department_id: str
    department_name: str
    service_scope: str
    jurisdiction_type: str
    jurisdiction_mapping: str
    jurisdiction_talukas: list[str]
    contact_email_demo: str
    contact_channel: str
    mock_webhook_id: str
    is_real_contact: bool
    notes: str


@dataclass(frozen=True)
class HistoryRow:
    grievance_id: str
    complaint_text: str
    category_id: str
    category: str
    subcategory: str
    department_id: str
    broad_location_taluka: str
    broad_location_locality: str
    submission_date: str
    resolution_date: str | None
    status: str
    resolution_text: str | None
    citizen_feedback: str
    priority: str
    sla_days: int
    sensitive: bool
    identity_hiding: bool
    resolution_actor: str
    ai_auto_closed: bool
    data_origin: str


CATEGORY_COLUMNS = {
    "category_id",
    "category",
    "subcategory",
    "responsible_department_id",
    "responsible_department",
    "default_assignee",
    "sla_days",
    "sensitive",
    "identity_hiding",
    "default_priority",
    "auto_resolution_allowed",
    "policy_note",
}
DEPARTMENT_COLUMNS = {
    "department_id",
    "department_name",
    "service_scope",
    "jurisdiction_type",
    "jurisdiction_mapping",
    "contact_email_demo",
    "contact_channel",
    "mock_webhook_id",
    "is_real_contact",
    "notes",
}
HISTORY_COLUMNS = {
    "grievance_id",
    "complaint_text",
    "category_id",
    "category",
    "subcategory",
    "department_id",
    "broad_location_taluka",
    "broad_location_locality",
    "submission_date",
    "resolution_date",
    "status",
    "resolution_text",
    "citizen_feedback",
    "priority",
    "sla_days",
    "sensitive",
    "identity_hiding",
    "resolution_actor",
    "ai_auto_closed",
    "data_origin",
}


def _read_rows(path: Path, required: set[str]) -> Iterator[dict[str, str]]:
    if not path.exists():
        raise DataFormatError(f"required data file is missing: {path}")
    with path.open(encoding=ENCODING, newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = required - headers
        if missing:
            raise DataFormatError(
                f"{path.name} is missing required columns: {sorted(missing)}"
            )
        for row in reader:
            yield row


def parse_category_master(path: Path) -> list[CategoryRow]:
    rows: list[CategoryRow] = []
    seen: set[str] = set()
    for raw in _read_rows(path, CATEGORY_COLUMNS):
        cid = raw["category_id"].strip()
        if not cid:
            continue
        if cid in seen:
            raise DataFormatError(f"duplicate category_id {cid!r} in {path.name}")
        seen.add(cid)
        rows.append(
            CategoryRow(
                category_id=cid,
                category=raw["category"].strip(),
                subcategory=raw["subcategory"].strip(),
                responsible_department_id=raw["responsible_department_id"].strip(),
                responsible_department=raw["responsible_department"].strip(),
                default_assignee=raw["default_assignee"].strip(),
                sla_days=parse_int(raw["sla_days"], field="sla_days", row_id=cid),
                sensitive=parse_bool(raw["sensitive"], field="sensitive", row_id=cid),
                identity_hiding=parse_bool(
                    raw["identity_hiding"], field="identity_hiding", row_id=cid
                ),
                default_priority=raw["default_priority"].strip(),
                auto_resolution_allowed=parse_bool(
                    raw["auto_resolution_allowed"],
                    field="auto_resolution_allowed",
                    row_id=cid,
                ),
                policy_note=raw["policy_note"].strip(),
            )
        )
    if not rows:
        raise DataFormatError(f"{path.name} contains no category rows")
    return rows


def parse_department_directory(path: Path) -> list[DepartmentRow]:
    rows: list[DepartmentRow] = []
    seen: set[str] = set()
    for raw in _read_rows(path, DEPARTMENT_COLUMNS):
        did = raw["department_id"].strip()
        if not did:
            continue
        if did in seen:
            raise DataFormatError(f"duplicate department_id {did!r} in {path.name}")
        seen.add(did)
        rows.append(
            DepartmentRow(
                department_id=did,
                department_name=raw["department_name"].strip(),
                service_scope=raw["service_scope"].strip(),
                jurisdiction_type=raw["jurisdiction_type"].strip(),
                jurisdiction_mapping=raw["jurisdiction_mapping"].strip(),
                jurisdiction_talukas=parse_jurisdiction_talukas(
                    raw["jurisdiction_mapping"]
                ),
                contact_email_demo=raw["contact_email_demo"].strip(),
                contact_channel=raw["contact_channel"].strip(),
                mock_webhook_id=raw["mock_webhook_id"].strip(),
                is_real_contact=parse_bool(
                    raw["is_real_contact"], field="is_real_contact", row_id=did
                ),
                notes=raw["notes"].strip(),
            )
        )
    if not rows:
        raise DataFormatError(f"{path.name} contains no department rows")
    return rows


def parse_grievance_history(path: Path) -> list[HistoryRow]:
    rows: list[HistoryRow] = []
    for raw in _read_rows(path, HISTORY_COLUMNS):
        gid = raw["grievance_id"].strip()
        if not gid:
            continue
        rows.append(
            HistoryRow(
                grievance_id=gid,
                complaint_text=raw["complaint_text"],
                category_id=raw["category_id"].strip(),
                category=raw["category"].strip(),
                subcategory=raw["subcategory"].strip(),
                department_id=raw["department_id"].strip(),
                broad_location_taluka=raw["broad_location_taluka"].strip(),
                broad_location_locality=raw["broad_location_locality"].strip(),
                submission_date=raw["submission_date"].strip(),
                resolution_date=raw["resolution_date"].strip() or None,
                status=raw["status"].strip(),
                resolution_text=raw["resolution_text"].strip() or None,
                citizen_feedback=raw["citizen_feedback"].strip(),
                priority=raw["priority"].strip(),
                sla_days=parse_int(raw["sla_days"], field="sla_days", row_id=gid),
                sensitive=parse_bool(raw["sensitive"], field="sensitive", row_id=gid),
                identity_hiding=parse_bool(
                    raw["identity_hiding"], field="identity_hiding", row_id=gid
                ),
                resolution_actor=raw["resolution_actor"].strip(),
                ai_auto_closed=parse_bool(
                    raw["ai_auto_closed"], field="ai_auto_closed", row_id=gid
                ),
                data_origin=raw["data_origin"].strip(),
            )
        )
    return rows
