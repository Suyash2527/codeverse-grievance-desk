"""The citizen conversation, up to the moment a ticket exists.

A grievance is created only when the citizen confirms the draft. Until then
the conversation lives in intake_session: the turns, the structured draft, and
what is still missing.

Each new message is folded into the accumulated text and the draft is rebuilt
from the whole conversation, so answering a follow-up question improves the
draft rather than replacing it with a fragment ("Mukhed Town" alone is not a
grievance).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.intake import run_intake
from app.agents.state import PipelineState
from app.config import settings
from app.llm.provider import LLMProvider, StubProvider, get_provider
from app.models import IntakeSession

SUPPORTED_LANGUAGES = {"mr": "Marathi", "hi": "Hindi", "en": "English"}

#: Said to the citizen when a draft is complete enough to file.
CONFIRM_PROMPT = {
    "mr": "मी खालील तक्रार नोंदवू का? कृपया तपासून पुष्टी करा.",
    "hi": "क्या मैं यह शिकायत दर्ज करूँ? कृपया जाँच कर पुष्टि करें.",
    "en": "Shall I file this grievance? Please check the details and confirm.",
}

NEEDS_MORE = {
    "mr": "नोंदणीपूर्वी आणखी काही माहिती हवी आहे:",
    "hi": "दर्ज करने से पहले कुछ और जानकारी चाहिए:",
    "en": "I need a little more before filing this:",
}

#: Said when no API key is configured and the text is not English. The offline
#: classifier has no translation, and pretending otherwise would be worse than
#: saying so.
NO_TRANSLATION = {
    "mr": (
        "या डेमोमध्ये भाषांतर मॉडेल उपलब्ध नाही, त्यामुळे तक्रार मानवी "
        "अधिकाऱ्याकडे पाठवली जाईल."
    ),
    "hi": (
        "इस डेमो में अनुवाद मॉडल उपलब्ध नहीं है, इसलिए शिकायत मानव अधिकारी "
        "को भेजी जाएगी."
    ),
    "en": (
        "No language model is configured in this demo, so this will be routed "
        "to a human officer rather than classified automatically."
    ),
}


def new_session_key() -> str:
    return f"ses_{uuid.uuid4().hex[:12]}"


def get_session_row(session: Session, session_key: str) -> IntakeSession | None:
    return session.scalar(
        select(IntakeSession).where(IntakeSession.session_key == session_key)
    )


def _accumulated_text(transcript: list[dict[str, Any]]) -> str:
    return " ".join(
        turn["text"] for turn in transcript if turn.get("role") == "citizen"
    ).strip()


def add_message(
    session: Session,
    *,
    text: str,
    language: str = "en",
    session_key: str | None = None,
    source: str = "text",
    provider: LLMProvider | None = None,
) -> dict[str, Any]:
    """Add a citizen turn and rebuild the draft. Creates no grievance."""
    language = language if language in SUPPORTED_LANGUAGES else "en"
    row = get_session_row(session, session_key) if session_key else None
    if row is None:
        row = IntakeSession(
            session_key=new_session_key(),
            language=language,
            transcript=[],
            draft={},
            missing_details=[],
        )
        session.add(row)
        session.flush()

    transcript = list(row.transcript or [])
    transcript.append(
        {
            "role": "citizen",
            "text": text,
            "source": source,
            "language": language,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )

    llm = provider or get_provider()
    state: PipelineState = {
        "raw_text": _accumulated_text(transcript),
        "language": language,
    }
    run_intake(session, state, provider=llm)

    draft = state.get("draft") or {}
    missing = list(state.get("missing_details") or [])

    offline_without_translation = (
        isinstance(llm, StubProvider) and language != "en"
    )

    if offline_without_translation:
        reply = NO_TRANSLATION[language]
        ready = False
    elif missing:
        reply = NEEDS_MORE[language] + " " + "; ".join(str(m) for m in missing)
        ready = False
    else:
        reply = CONFIRM_PROMPT[language]
        ready = True

    transcript.append(
        {
            "role": "system",
            "text": reply,
            "language": language,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )

    row.transcript = transcript
    row.draft = draft
    row.missing_details = missing
    row.language = language
    session.flush()
    session.commit()

    return {
        "session_key": row.session_key,
        "language": language,
        "reply": reply,
        "draft": draft,
        "missing_details": missing,
        "ready_to_confirm": ready,
        "confidence": state.get("intake_confidence"),
        "model": state.get("model"),
        "transcript": transcript,
        "translation_available": not offline_without_translation,
    }


#: The simulated channels, and how the timeline names them.
SIMULATED_CHANNELS = {"whatsapp": "WhatsApp", "call": "a phone call"}


def channel_of(transcript: list[dict[str, Any]]) -> str:
    """The channel the citizen first spoke through. Defaults to the web chat."""
    for turn in transcript:
        if turn.get("role") == "citizen":
            return str(turn.get("source") or "text")
    return "text"


def _record_channel(session: Session, reference: str, transcript: list[dict[str, Any]]) -> None:
    """Note on the case's timeline that it arrived through a simulated channel.

    Kept in the audit log rather than a new grievance column, so no schema
    change was needed. The citizen is the actor: they chose the channel.
    """
    channel = channel_of(transcript)
    if channel not in SIMULATED_CHANNELS:
        return
    from app.policy.guards import Actor, build_audit_entry
    from app.services.grievance_service import record_audit

    record_audit(
        session,
        build_audit_entry(
            actor=Actor.CITIZEN,
            actor_id=reference,
            action="RECEIVED_VIA_" + channel.upper(),
            target=reference,
            reasoning=(
                f"Filed through {SIMULATED_CHANNELS[channel]} (simulated channel). "
                "The intake agent was real; no message or call left this system."
            ),
            rule_applied="RULE_8_MOCK_CONTACTS_ONLY",
        ),
    )


def confirm(
    session: Session,
    *,
    session_key: str,
    citizen_name: str | None = None,
    citizen_phone: str | None = None,
    provider: LLMProvider | None = None,
) -> dict[str, Any]:
    """The citizen confirms the draft: now, and only now, a ticket is created.

    The rest of the pipeline then runs from the confirmed draft rather than
    re-reading the raw text, so what is filed is exactly what was shown.
    """
    from app.agents.graph import run_pipeline_from_draft

    row = get_session_row(session, session_key)
    if row is None:
        raise LookupError(f"unknown intake session {session_key}")
    if row.confirmed_at is not None:
        raise ValueError("this draft has already been filed")

    state = run_pipeline_from_draft(
        session,
        draft=dict(row.draft or {}),
        raw_text=_accumulated_text(list(row.transcript or [])),
        language=row.language,
        citizen_name=citizen_name,
        citizen_phone=citizen_phone,
        provider=provider,
    )

    row.confirmed_at = datetime.now(timezone.utc)
    reference = state.get("grievance_ref")
    if reference:
        from app.models import Grievance

        grievance = session.scalar(
            select(Grievance).where(Grievance.reference_no == reference)
        )
        if grievance:
            row.grievance_id = grievance.id
        _record_channel(session, reference, list(row.transcript or []))
    session.flush()
    session.commit()

    return {
        "session_key": row.session_key,
        "reference_no": reference,
        "status": state.get("gate", {}).get("outcome"),
        "gate": state.get("gate"),
        "filed": reference is not None,
    }
