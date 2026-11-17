"""Create the schema and load the CSVs in DATA_DIR.

    python scripts/load_data.py

Re-running it is safe: configuration tables are replaced, not appended, which
is also how a replacement CSV is applied.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db, is_postgres  # noqa: E402
from app.loaders import reload_reference_data  # noqa: E402


def main() -> int:
    print(f"data dir : {settings.data_dir}")
    print(f"database : {settings.database_url.split('@')[-1]}")
    init_db()
    with SessionLocal() as session:
        report = reload_reference_data(session, settings)

    print(
        f"loaded   : {report.categories} categories, "
        f"{report.departments} departments, {report.history} history rows"
    )
    for warning in report.warnings:
        print(f"warning  : {warning}")
    if not is_postgres():
        print(
            "note     : not running on Postgres, so pgvector similarity search "
            "is unavailable. Policy, routing and SLA logic are unaffected."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
