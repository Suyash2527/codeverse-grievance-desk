"""Duplicate detection: grouping, never merging.

Several citizens reporting the same burst pipe is one incident and several
grievances. This module links them to a shared incident so a department can
act once, and it changes nothing else: every grievance keeps its own
reference number, its own status, its own SLA deadline and its own
notifications. No grievance is ever deleted, closed, or hidden because
another one looks like it.

A group is a *suggestion* until an officer confirms it. Confirmation is
recorded on the incident with the officer's ID.

Grouping requires all three to agree:
  1. the same category (policy must not be crossed by a grouping),
  2. the same place, at the configured granularity,
  3. submission within the configured time window,
and then semantic similarity above the configured threshold.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Grievance, Incident
from app.policy.guards import Actor, build_audit_entry
from app.rag.embeddings import cosine_similarity, embed_text
from app.services.grievance_service import record_audit

#: Cosine values are not comparable across embedding spaces, so the default
#: threshold depends on which one is in use. Semantic embeddings place
#: paraphrases around 0.85-0.95; the offline lexical hash embedding scores the
#: same pair far lower because it only sees shared tokens. One fixed number
#: would either group nothing offline or group everything online.
SEMANTIC_THRESHOLD_DEFAULT = 0.72
LEXICAL_THRESHOLD_DEFAULT = 0.45


def default_threshold() -> float:
    from app.rag.embeddings import OPENAI_METHOD, embedding_method

    return (
        SEMANTIC_THRESHOLD_DEFAULT
        if embedding_method() == OPENAI_METHOD
        else LEXICAL_THRESHOLD_DEFAULT
    )


def similarity_threshold() -> float:
    configured = os.environ.get("DUPLICATE_SIMILARITY_THRESHOLD")
    return float(configured) if configured else default_threshold()


WINDOW_DAYS = int(os.environ.get("DUPLICATE_WINDOW_DAYS", "7"))

#: "locality" groups a street; "taluka" groups a whole block. Locality is the
#: default because grouping too broadly hides distinct problems.
LOCATION_GRANULARITY = os.environ.get("DUPLICATE_LOCATION_GRANULARITY", "locality")


@dataclass
class CandidateGroup:
    category_id: str
    taluka: str | None
    locality: str | None
    members: list[Grievance]
    similarity: float

    @property
    def size(self) -> int:
        return len(self.members)


def _location_key(grievance: Grievance) -> tuple[str | None, str | None]:
    if LOCATION_GRANULARITY == "taluka":
        return (grievance.taluka, None)
    return (grievance.taluka, grievance.locality)


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _text_of(grievance: Grievance) -> str:
    return grievance.normalised_text_en or grievance.complaint_text


def _vector(grievance: Grievance) -> list[float]:
    """The case's embedding, computed and cached on first use."""
    if grievance.embedding:
        return list(grievance.embedding)
    vector = embed_text(_text_of(grievance))
    grievance.embedding = vector
    return vector


def find_candidate_groups(
    session: Session, *, now: datetime | None = None
) -> list[CandidateGroup]:
    """Find groups of live grievances that appear to describe one incident."""
    moment = now or datetime.now(timezone.utc)
    window_start = moment - timedelta(days=WINDOW_DAYS)

    cases = [
        g
        for g in session.scalars(select(Grievance))
        if (_aware(g.created_at) or moment) >= window_start
    ]

    buckets: dict[tuple, list[Grievance]] = {}
    for grievance in cases:
        key = (grievance.category_id, *_location_key(grievance))
        buckets.setdefault(key, []).append(grievance)

    groups: list[CandidateGroup] = []
    for key, members in buckets.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda g: _aware(g.created_at) or moment)

        vectors = {g.reference_no: _vector(g) for g in members}
        assigned: set[str] = set()
        threshold = similarity_threshold()

        for anchor in members:
            if anchor.reference_no in assigned:
                continue
            cluster = [anchor]
            scores: list[float] = []
            for other in members:
                if other.reference_no == anchor.reference_no:
                    continue
                if other.reference_no in assigned:
                    continue
                similarity = cosine_similarity(
                    vectors[anchor.reference_no], vectors[other.reference_no]
                )
                if similarity >= threshold:
                    cluster.append(other)
                    scores.append(similarity)
            if len(cluster) > 1:
                for member in cluster:
                    assigned.add(member.reference_no)
                groups.append(
                    CandidateGroup(
                        category_id=key[0],
                        taluka=key[1],
                        locality=key[2],
                        members=cluster,
                        similarity=round(sum(scores) / len(scores), 4) if scores else 0.0,
                    )
                )
    return groups


def _next_incident_ref(session: Session) -> str:
    count = len(list(session.scalars(select(Incident.id)))) + 1
    return f"INC-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{count:03d}"


def group_duplicates(
    session: Session, *, now: datetime | None = None
) -> dict[str, Any]:
    """Link candidate groups to incidents, leaving every grievance intact.

    Returns what was grouped so the officer view can show it. Each member
    keeps its own reference, status and deadline; the incident is additive
    metadata and carries no authority over any case.
    """
    moment = now or datetime.now(timezone.utc)
    created: list[dict[str, Any]] = []

    for group in find_candidate_groups(session, now=moment):
        existing = next(
            (member.incident_id for member in group.members if member.incident_id),
            None,
        )
        if existing is not None:
            incident = session.get(Incident, existing)
        else:
            dates = [
                (_aware(m.created_at) or moment).date() for m in group.members
            ]
            incident = Incident(
                incident_ref=_next_incident_ref(session),
                category_id=group.category_id,
                taluka=group.taluka,
                locality=group.locality,
                window_start=min(dates),
                window_end=max(dates),
                similarity=group.similarity,
                created_at=moment,
            )
            session.add(incident)
            session.flush()

        newly_linked = []
        for member in group.members:
            if member.incident_id == incident.id:
                continue
            member.incident_id = incident.id
            newly_linked.append(member.reference_no)
            record_audit(
                session,
                build_audit_entry(
                    actor=Actor.AI_SYSTEM,
                    action="LINK_TO_INCIDENT",
                    target=member.reference_no,
                    reasoning=(
                        f"Grouped with {len(group.members) - 1} other grievance(s) "
                        f"as incident {incident.incident_ref} "
                        f"(same category and location, within {WINDOW_DAYS} days, "
                        f"mean similarity {group.similarity:.2f}). "
                        f"This grievance keeps its own reference number, status, "
                        f"deadline and notifications; nothing was merged or closed."
                    ),
                    model="duplicate-grouping",
                    confidence=group.similarity,
                    rule_applied="DUPLICATES_GROUPED_NEVER_MERGED",
                    timestamp=moment,
                ),
            )
        session.flush()

        if newly_linked:
            created.append(
                {
                    "incident_ref": incident.incident_ref,
                    "category_id": incident.category_id,
                    "taluka": incident.taluka,
                    "locality": incident.locality,
                    "similarity": group.similarity,
                    "members": [m.reference_no for m in group.members],
                    "newly_linked": newly_linked,
                    "confirmed_by": incident.confirmed_by,
                }
            )

    session.commit()
    return {
        "grouped_at": moment.isoformat(),
        "incidents": created,
        "settings": {
            "similarity_threshold": similarity_threshold(),
            "window_days": WINDOW_DAYS,
            "location_granularity": LOCATION_GRANULARITY,
        },
    }


def list_incidents(session: Session) -> list[dict[str, Any]]:
    """Incidents with their members. Members are listed, never collapsed."""
    out: list[dict[str, Any]] = []
    for incident in session.scalars(select(Incident).order_by(Incident.id.desc())):
        members = list(
            session.scalars(
                select(Grievance).where(Grievance.incident_id == incident.id)
            )
        )
        out.append(
            {
                "incident_ref": incident.incident_ref,
                "id": incident.id,
                "category_id": incident.category_id,
                "taluka": incident.taluka,
                "locality": incident.locality,
                "window_start": incident.window_start.isoformat(),
                "window_end": incident.window_end.isoformat(),
                "similarity": incident.similarity,
                "confirmed_by": incident.confirmed_by,
                "member_count": len(members),
                "members": [
                    {
                        "reference_no": m.reference_no,
                        "status": m.status,
                        "priority": m.priority,
                        "sla_due_at": m.sla_due_at.isoformat() if m.sla_due_at else None,
                    }
                    for m in members
                ],
                "note": (
                    "Grouped for coordination only. Each grievance keeps its own "
                    "reference number, status, deadline and notifications."
                ),
            }
        )
    return out


def confirm_incident(
    session: Session, *, incident_id: int, officer_id: str, note: str
) -> dict[str, Any]:
    """Record that an officer confirmed a suggested grouping."""
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise LookupError(f"unknown incident {incident_id}")
    incident.confirmed_by = officer_id
    session.flush()

    for member in session.scalars(
        select(Grievance).where(Grievance.incident_id == incident.id)
    ):
        record_audit(
            session,
            build_audit_entry(
                actor=Actor.OFFICER,
                actor_id=officer_id,
                action="CONFIRM_INCIDENT_GROUPING",
                target=member.reference_no,
                reasoning=(
                    f"Officer confirmed grouping into {incident.incident_ref}: {note}"
                ),
                rule_applied="HUMAN_CONFIRMED_GROUPING",
            ),
        )
    session.commit()
    return {"incident_ref": incident.incident_ref, "confirmed_by": officer_id}
