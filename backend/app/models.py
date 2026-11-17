"""Database schema.

Two groups of tables:

* Configuration, loaded from the supplied CSVs at runtime and reloaded
  wholesale when a CSV is replaced: category_master, department_directory,
  grievance_history.
* Runtime state produced by the system: grievance, citizen_contact,
  intake_session, decision, audit_log, incident, sla_alert, notification.

Portability note: the column types below work on both Postgres (production,
with pgvector) and SQLite (tests). That keeps the hard-rule test suite runnable
with no database server, while the real deployment uses Postgres + pgvector.
Similarity search itself requires Postgres.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class Vector(TypeDecorator):
    """pgvector column on Postgres, JSON list elsewhere.

    SQLite has no vector type, so the tests store the embedding as JSON. The
    dialect decides; application code just assigns a list of floats.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int, *args, **kwargs) -> None:
        self.dim = dim
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector as PGVector

            return dialect.type_descriptor(PGVector(self.dim))
        # none_as_null is essential: SQLAlchemy's JSON type otherwise stores a
        # Python None as JSON null, which is NOT SQL NULL. An "embedding IS
        # NOT NULL" filter would then match every un-embedded row and retrieval
        # would return meaningless zero-similarity evidence.
        return dialect.type_descriptor(JSON(none_as_null=True))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Configuration tables (reloaded from CSV)
# --------------------------------------------------------------------------


class CategoryMaster(Base):
    """grievance_category_master.csv. The policy source of truth.

    Policy is always read from here at decision time, never from the copies
    denormalised onto history or ticket rows.
    """

    __tablename__ = "category_master"

    category_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(128))
    subcategory: Mapped[str] = mapped_column(String(256))
    responsible_department_id: Mapped[str] = mapped_column(String(32), index=True)
    responsible_department: Mapped[str] = mapped_column(String(256))
    default_assignee: Mapped[str] = mapped_column(String(256))
    sla_days: Mapped[int] = mapped_column(Integer)
    sensitive: Mapped[bool] = mapped_column(Boolean, index=True)
    identity_hiding: Mapped[bool] = mapped_column(Boolean, index=True)
    default_priority: Mapped[str] = mapped_column(String(16))
    auto_resolution_allowed: Mapped[bool] = mapped_column(Boolean)
    policy_note: Mapped[str] = mapped_column(Text, default="")


class DepartmentDirectory(Base):
    """department_directory.csv. Routing targets and mock contact channels."""

    __tablename__ = "department_directory"

    department_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    department_name: Mapped[str] = mapped_column(String(256))
    service_scope: Mapped[str] = mapped_column(Text, default="")
    jurisdiction_type: Mapped[str] = mapped_column(String(64), default="")
    jurisdiction_mapping: Mapped[str] = mapped_column(Text, default="")
    jurisdiction_talukas: Mapped[list] = mapped_column(JSON, default=list)
    contact_email_demo: Mapped[str] = mapped_column(String(256), default="")
    contact_channel: Mapped[str] = mapped_column(String(256), default="")
    mock_webhook_id: Mapped[str] = mapped_column(String(128), default="")
    is_real_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class GrievanceHistory(Base):
    """mock_grievance_history.csv plus its embedding, used as RAG evidence."""

    __tablename__ = "grievance_history"

    grievance_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    complaint_text: Mapped[str] = mapped_column(Text)
    category_id: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(128))
    subcategory: Mapped[str] = mapped_column(String(256))
    department_id: Mapped[str] = mapped_column(String(32), index=True)
    broad_location_taluka: Mapped[str] = mapped_column(String(128), index=True)
    broad_location_locality: Mapped[str] = mapped_column(String(128), index=True)
    submission_date: Mapped[date] = mapped_column(Date, index=True)
    resolution_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    resolution_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citizen_feedback: Mapped[str] = mapped_column(String(64), default="")
    priority: Mapped[str] = mapped_column(String(16))
    sla_days: Mapped[int] = mapped_column(Integer)
    sensitive: Mapped[bool] = mapped_column(Boolean)
    identity_hiding: Mapped[bool] = mapped_column(Boolean)
    resolution_actor: Mapped[str] = mapped_column(String(32))
    ai_auto_closed: Mapped[bool] = mapped_column(Boolean)
    data_origin: Mapped[str] = mapped_column(String(64), default="")
    #: Days from submission to resolution, precomputed for the SLA predictor.
    resolution_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


# --------------------------------------------------------------------------
# Runtime tables
# --------------------------------------------------------------------------


class CitizenContact(Base):
    """The only table holding complainant identity.

    Kept separate so department-facing queries simply never join it; masking
    is then a guarantee of the data model as well as of the serializer.
    """

    __tablename__ = "citizen_contact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    citizen_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    citizen_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    citizen_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(16), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Grievance(Base):
    """A live grievance. Every one keeps its own reference number and status.

    sla_days and sla_due_at are snapshotted at creation so the citizen-facing
    promise does not move; policy flags are deliberately NOT snapshotted for
    enforcement purposes, which always re-reads category_master.
    """

    __tablename__ = "grievance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    complaint_text: Mapped[str] = mapped_column(Text)
    complaint_language: Mapped[str] = mapped_column(String(16), default="en")
    normalised_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("category_master.category_id"), index=True
    )
    department_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="Submitted", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    taluka: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    locality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    citizen_contact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("citizen_contact.id"), nullable=True
    )
    identity_masked: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_days: Mapped[int] = mapped_column(Integer)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    incident_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("incident.id"), nullable=True, index=True
    )
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)
    #: AI-produced, stored already wrapped by label_ai_output so the officer
    #: view cannot render either as a verified fact (rule 6).
    ai_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_sentiment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    embedding: Mapped[list | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class IntakeSession(Base):
    """A conversation in progress. A ticket exists only after confirmation."""

    __tablename__ = "intake_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    transcript: Mapped[list] = mapped_column(JSON, default=list)
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_details: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    grievance_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("grievance.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Decision(Base):
    """One pipeline decision, with the evidence that produced it (rule 5)."""

    __tablename__ = "decision"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grievance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grievance.id"), index=True
    )
    gate_outcome: Mapped[str] = mapped_column(String(32))
    policy_rule_applied: Mapped[str] = mapped_column(String(128))
    policy_reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    confidence_threshold: Mapped[float] = mapped_column(Float)
    retrieved_case_ids: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128))
    rationale: Mapped[str] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only record of every AI and human action (rule 4)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(128), index=True)
    reasoning: Mapped[str] = mapped_column(Text)
    rule_applied: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Incident(Base):
    """A group of grievances believed to describe the same real-world event.

    Grouping is additive: member grievances keep their own reference numbers,
    statuses and notifications. Nothing is merged or dropped.
    """

    __tablename__ = "incident"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category_id: Mapped[str] = mapped_column(String(32))
    taluka: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locality: Mapped[str | None] = mapped_column(String(128), nullable=True)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SlaAlert(Base):
    """An escalation alert raised before a deadline, with its evidence."""

    __tablename__ = "sla_alert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grievance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grievance.id"), index=True
    )
    risk: Mapped[str] = mapped_column(String(32))
    predicted_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_p80_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    sla_days: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reason: Mapped[str] = mapped_column(Text, default="")
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Notification(Base):
    """Simulated outbound message. Stores the masked payload actually sent.

    Nothing leaves the process: delivery is recorded here and, when configured,
    posted to an n8n webhook. All addresses are placeholders (rule 8).
    """

    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grievance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("grievance.id"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32))
    destination: Mapped[str] = mapped_column(String(256))
    mock_webhook_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    identity_masked: Mapped[bool] = mapped_column(Boolean, default=False)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
