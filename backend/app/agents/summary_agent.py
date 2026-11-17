"""Summary Agent.

Produces the one-line summary and sentiment the officer queue shows. Both are
stored already wrapped by label_ai_output, so there is no path by which the
UI can receive them unlabelled (rule 6).

Sentiment is reported for triage only. It never feeds the policy gate and
never affects priority: an angry complaint about a pothole is still a pothole,
and a politely worded safety threat is still a safety threat.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.state import PipelineState
from app.llm.provider import LLMProvider, Completion, get_provider, tokenize
from app.models import Grievance
from app.observability.trace import record, span
from app.policy.guards import label_ai_output

SUMMARY_SPAN = "summary.generate"

SYSTEM_PROMPT = """You summarise a citizen grievance for a government officer
triaging a queue.

Rules:
- summary is ONE sentence, under 140 characters, in English, stating only what
  the citizen reported. Add no facts, no diagnosis, no blame, no liability.
- sentiment describes the citizen's tone, not the severity of the issue.
- Never recommend closing, rejecting or dismissing the grievance.

Return a single JSON object and nothing else."""

SCHEMA_HINT = """{
  "summary": "one sentence under 140 characters",
  "sentiment": "ANGRY | DISTRESSED | NEUTRAL | APPRECIATIVE",
  "sentiment_confidence": 0.0,
  "key_points": ["short phrase"]
}"""

# Tone vocabulary for the offline path only. These are English tone words, not
# policy data: no category, flag or routing decision depends on them.
NEGATIVE_TONE = {
    "angry", "furious", "disgusted", "unacceptable", "ignored", "repeatedly",
    "again", "still", "worst", "terrible", "useless", "negligence", "fed",
    "frustrated", "complained", "nobody", "no one", "delay", "delayed",
}
DISTRESS_TONE = {
    "urgent", "emergency", "danger", "dangerous", "unsafe", "afraid", "fear",
    "scared", "risk", "help", "immediately", "confidential", "threat", "safety",
}
POSITIVE_TONE = {"thank", "thanks", "grateful", "appreciate", "please", "kindly"}


def _offline_summary(text: str) -> dict[str, Any]:
    """Extractive fallback: first sentence, plus lexical tone."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    first = re.split(r"(?<=[.!?])\s+", cleaned)[0] if cleaned else ""
    summary = (first[:137] + "...") if len(first) > 140 else first

    tokens = set(tokenize(cleaned))
    if tokens & DISTRESS_TONE:
        sentiment, confidence = "DISTRESSED", 0.5
    elif tokens & NEGATIVE_TONE:
        sentiment, confidence = "ANGRY", 0.45
    elif tokens & POSITIVE_TONE:
        sentiment, confidence = "APPRECIATIVE", 0.4
    else:
        sentiment, confidence = "NEUTRAL", 0.3

    return {
        "summary": summary or "No complaint text was provided.",
        "sentiment": sentiment,
        "sentiment_confidence": confidence,
        "key_points": [],
    }


def run_summary(
    session: Session, state: PipelineState, *, provider: LLMProvider | None = None
) -> PipelineState:
    llm = provider or get_provider()
    draft = state.get("draft") or {}
    text = draft.get("description") or state.get("raw_text", "")

    with span(SUMMARY_SPAN, characters=len(text)) as current:
        from app.llm.provider import StubProvider

        if isinstance(llm, StubProvider):
            # The stub classifier answers a different question; use the
            # extractive fallback rather than pretending it summarised.
            payload = _offline_summary(text)
            model = "offline-extractive-summary"
        else:
            completion: Completion = llm.complete_json(
                system=SYSTEM_PROMPT,
                user=text,
                schema_hint=SCHEMA_HINT,
                context={},
            )
            payload = completion.as_json() or _offline_summary(text)
            model = completion.model

        summary = label_ai_output(payload.get("summary", ""), kind="summary", model=model)
        sentiment = label_ai_output(
            {
                "sentiment": payload.get("sentiment", "NEUTRAL"),
                "confidence": payload.get("sentiment_confidence", 0.0),
                "key_points": payload.get("key_points", []),
            },
            kind="sentiment",
            model=model,
        )
        record(current, summary=summary["value"], sentiment=sentiment["value"])

    reference = state.get("grievance_ref")
    if reference:
        grievance = (
            session.query(Grievance).filter_by(reference_no=reference).one_or_none()
        )
        if grievance is not None:
            grievance.ai_summary = summary
            grievance.ai_sentiment = sentiment
            session.flush()

    state["ai_summary"] = summary
    state["ai_sentiment"] = sentiment
    return state
