"""Finding a place name in what the citizen wrote.

Every place name is read from the loaded data at runtime:

* talukas come from department_directory.jurisdiction_mapping,
* localities come from the historical cases.

Nothing is hardcoded, so a replacement CSV with different geography works
with no code change. This runs as a deterministic backstop for the Intake
Agent: if the model does not pick up a location the citizen plainly stated,
routing should not depend on it having noticed.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DepartmentDirectory, GrievanceHistory


def known_talukas(session: Session) -> list[str]:
    names: set[str] = set()
    for mapping in session.scalars(select(DepartmentDirectory.jurisdiction_talukas)):
        for taluka in mapping or []:
            if taluka:
                names.add(taluka)
    for taluka in session.scalars(
        select(GrievanceHistory.broad_location_taluka).distinct()
    ):
        if taluka:
            names.add(taluka)
    return sorted(names)


def known_localities(session: Session) -> list[str]:
    return sorted(
        {
            locality
            for locality in session.scalars(
                select(GrievanceHistory.broad_location_locality).distinct()
            )
            if locality
        }
    )


def _find(text: str, candidates: Iterable[str]) -> str | None:
    """Longest whole-word match, so "Mukhed Town" wins over "Mukhed"."""
    lowered = (text or "").lower()
    best: str | None = None
    for candidate in candidates:
        pattern = rf"\b{re.escape(candidate.lower())}\b"
        if re.search(pattern, lowered):
            if best is None or len(candidate) > len(best):
                best = candidate
    return best


def locate(session: Session, text: str) -> dict[str, str | None]:
    """Extract a taluka and locality from free text, if either is named.

    Works on any script: the place names are matched as they appear in the
    data, and a complaint written in Marathi that names the place in Latin
    script still resolves.
    """
    locality = _find(text, known_localities(session))
    taluka = _find(text, known_talukas(session))

    if locality and not taluka:
        # A locality implies its taluka when the history agrees on one.
        talukas = {
            row
            for row in session.scalars(
                select(GrievanceHistory.broad_location_taluka)
                .where(GrievanceHistory.broad_location_locality == locality)
                .distinct()
            )
        }
        if len(talukas) == 1:
            taluka = talukas.pop()

    return {"taluka": taluka, "locality": locality}
