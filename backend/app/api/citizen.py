"""Citizen-facing API: chat intake, voice, tracking, dispute.

Two guarantees shape this module:

* No ticket exists until the citizen confirms the draft. Every endpoint
  before /confirm is conversation only.
* A citizen reading their own case is never masked. Masking protects a
  complainant from the department, not from themselves.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import AuditLog, Decision, Grievance
from app.policy.guards import Audience
from app.services import intake_session, speech
from app.services.grievance_service import reopen_on_dispute, serialize_grievance

router = APIRouter(prefix="/api", tags=["citizen"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024

#: Where a citizen turn came from. "whatsapp" and "call" are the simulated
#: channels: they run the real intake agent, but no message or call ever
#: reaches a real number (hard rule 8).
Source = Literal["text", "voice", "whatsapp", "call"]


class MessageIn(BaseModel):
    text: str = Field(min_length=1)
    language: str = "en"
    session_key: str | None = None
    source: Source = "text"


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=speech.MAX_TTS_CHARS)
    language: str = "en"


class ConfirmIn(BaseModel):
    citizen_name: str | None = None
    citizen_phone: str | None = None


class FeedbackIn(BaseModel):
    satisfied: bool
    note: str = Field(min_length=1)


@router.get("/intake/languages")
def get_languages() -> dict[str, Any]:
    """Languages the chat accepts, and whether transcription is available."""
    return {
        "languages": [
            {"code": code, "name": name}
            for code, name in intake_session.SUPPORTED_LANGUAGES.items()
        ],
        "voice_available": bool(settings.openai_api_key) or speech.available(settings),
        "translation_available": bool(settings.openai_api_key),
        "stt_model": _stt_model(),
        # spoken replies, used by the simulated phone-call channel
        "tts_available": speech.available(settings),
        "speech_provider": "sarvam" if speech.available(settings)
        else ("openai" if settings.openai_api_key else None),
    }


def _stt_model() -> str | None:
    if speech.available(settings):
        return settings.sarvam_stt_model
    return settings.stt_model if settings.openai_api_key else None


@router.post("/intake/message")
def post_message(
    body: MessageIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Add a citizen turn and return the updated draft. Files nothing."""
    return intake_session.add_message(
        session,
        text=body.text,
        language=body.language,
        session_key=body.session_key,
        source=body.source,
    )


@router.post("/intake/{session_key}/confirm")
def post_confirm(
    session_key: str, body: ConfirmIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """The citizen confirms: the ticket is created from the shown draft."""
    try:
        return intake_session.confirm(
            session,
            session_key=session_key,
            citizen_name=body.citizen_name,
            citizen_phone=body.citizen_phone,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/intake/transcribe")
async def post_transcribe(
    audio: UploadFile = File(...),
    language: str = Form(default="en"),
) -> dict[str, Any]:
    """Transcribe spoken Marathi, Hindi or English.

    Uses Sarvam when SARVAM_API_KEY is set, otherwise OpenAI. With neither
    this returns 503 rather than a fabricated transcript: a wrong transcript
    would become a filed grievance.
    """
    if not settings.openai_api_key and not speech.available(settings):
        raise HTTPException(
            status_code=503,
            detail=(
                "Speech-to-text is unavailable because neither SARVAM_API_KEY "
                "nor OPENAI_API_KEY is configured. Please type the complaint instead."
            ),
        )

    payload = await audio.read()
    if not payload:
        raise HTTPException(status_code=422, detail="the audio file is empty")
    if len(payload) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="the audio file is too large")

    if speech.available(settings):
        try:
            text = speech.transcribe(
                settings,
                payload,
                filename=audio.filename or "speech.webm",
                content_type=audio.content_type,
                language=language,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except speech.SpeechUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"text": text, "language": language, "model": settings.sarvam_stt_model}

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        result = client.audio.transcriptions.create(
            file=(audio.filename or "speech.webm", payload, audio.content_type),
            model=settings.stt_model,
            # Naming the language materially improves accuracy for Marathi
            # and Hindi over letting the model detect it.
            language=language if language in intake_session.SUPPORTED_LANGUAGES else "en",
        )
    except Exception as exc:  # pragma: no cover - depends on a live API
        raise HTTPException(
            status_code=502, detail=f"transcription failed: {exc}"
        ) from exc

    return {
        "text": getattr(result, "text", ""),
        "language": language,
        "model": settings.stt_model,
    }


@router.post("/intake/speak")
def post_speak(body: SpeakIn) -> Response:
    """Read a reply aloud, for the simulated phone call. Returns WAV audio.

    503 without a speech provider: the call screen then shows the reply as
    text instead, so the channel still works end to end.
    """
    if not speech.available(settings):
        raise HTTPException(
            status_code=503,
            detail="Spoken replies are unavailable because SARVAM_API_KEY is not configured.",
        )
    language = body.language if body.language in intake_session.SUPPORTED_LANGUAGES else "en"
    try:
        audio = speech.synthesise(settings, body.text, language=language)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except speech.SpeechUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


@router.get("/track/{reference_no}")
def track(reference_no: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Track a case by reference number, as the complainant sees it.

    Identity is not masked here: the citizen is reading their own grievance.
    The AI summary and rationale are still labelled as AI-generated.
    """
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(
            status_code=404, detail=f"no grievance found with reference {reference_no}"
        )

    payload = serialize_grievance(session, grievance, audience=Audience.CITIZEN_SELF)
    decision = session.scalar(
        select(Decision)
        .where(Decision.grievance_id == grievance.id)
        .order_by(Decision.id.desc())
    )
    history = session.scalars(
        select(AuditLog)
        .where(AuditLog.target == reference_no)
        .order_by(AuditLog.id)
    ).all()

    return payload | {
        "ai_summary": grievance.ai_summary,
        "decision": None
        if decision is None
        else {
            "outcome": decision.gate_outcome,
            "policy_reason": decision.policy_reason,
        },
        "awaiting_feedback": grievance.status in {"Resolved", "Closed"},
        "timeline": [
            {
                "at": entry.timestamp.isoformat(),
                "by": "System" if entry.actor == "AI_SYSTEM" else entry.actor.title(),
                "action": entry.action.replace("_", " ").lower(),
                "detail": entry.reasoning,
            }
            for entry in history
        ],
    }


@router.post("/track/{reference_no}/feedback")
def post_feedback(
    reference_no: str, body: FeedbackIn, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Confirm or dispute a resolution. A dispute reopens the case."""
    grievance = session.scalar(
        select(Grievance).where(Grievance.reference_no == reference_no)
    )
    if grievance is None:
        raise HTTPException(status_code=404, detail=f"unknown reference {reference_no}")

    if body.satisfied:
        from app.policy.guards import Actor, build_audit_entry
        from app.services.grievance_service import record_audit

        record_audit(
            session,
            build_audit_entry(
                actor=Actor.CITIZEN,
                actor_id=grievance.reference_no,
                action="CONFIRM_RESOLUTION",
                target=grievance.reference_no,
                reasoning=f"Citizen confirmed the resolution: {body.note}",
                rule_applied="CITIZEN_CONFIRMED_RESOLUTION",
            ),
        )
        session.commit()
        return {
            "reference_no": grievance.reference_no,
            "status": grievance.status,
            "reopened": False,
        }

    reopen_on_dispute(session, grievance=grievance, citizen_note=body.note)
    session.commit()
    return {
        "reference_no": grievance.reference_no,
        "status": grievance.status,
        "reopened": True,
        "reopened_count": grievance.reopened_count,
    }
