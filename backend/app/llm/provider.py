"""LLM access behind one adapter.

Two implementations:

* OpenAIProvider  - used whenever OPENAI_API_KEY is present.
* StubProvider    - deterministic, offline, no network. Used when no key is
  configured, which is how the test suite and an offline demo run.

The stub is not a mock that returns canned answers for fixed inputs: it scores
the citizen text against the category master actually loaded, so it still has
no hardcoded category knowledge and still follows a swapped CSV. Its
classification is weaker than the model's, and it reports a low confidence to
say so, which routes borderline cases to the human queue exactly as the policy
intends.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from app.config import settings

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but", "in",
    "on", "at", "to", "for", "of", "with", "my", "our", "we", "i", "there",
    "this", "that", "it", "has", "have", "been", "not", "no", "please", "from",
    "near", "by", "be", "do", "does", "did", "as", "so", "very", "some", "any",
}


@dataclass(frozen=True)
class Completion:
    """One model response plus what is needed for the audit trail."""

    text: str
    model: str
    confidence: float
    raw: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return {}


class LLMProvider(Protocol):
    name: str

    def complete_json(
        self, *, system: str, user: str, schema_hint: str, context: dict[str, Any]
    ) -> Completion:
        """Return a JSON object response."""


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[\w']+", (text or "").lower()) if t not in STOPWORDS]


# --------------------------------------------------------------------------
# Offline deterministic provider
# --------------------------------------------------------------------------


class StubProvider:
    """Deterministic classifier used when no API key is configured.

    Two strategies, in order:

    1. **Nearest-neighbour vote over the district's own history.** The
       district has already classified 800 complaints by hand; a new one is
       matched against that record and the similar cases vote on the
       category, weighted by similarity. This is what makes an offline demo
       actually work on complaints nobody has seen.
    2. **Word overlap with the category names**, used only when there is no
       usable history. Weak, and it reports a low confidence to say so.

    Confidence is the winning share of the vote scaled by how similar the
    evidence actually was, so a complaint unlike anything in the record scores
    low and lands in human review rather than being auto-resolved on a guess.
    """

    name = "stub-offline-classifier"

    #: Below this similarity a neighbour is too weak to vote.
    MIN_NEIGHBOUR_SIMILARITY = 0.25

    def _vote(
        self, neighbours: Sequence[dict[str, Any]], user: str
    ) -> Completion | None:
        usable = [
            n
            for n in neighbours
            if float(n.get("similarity") or 0) >= self.MIN_NEIGHBOUR_SIMILARITY
        ]
        if not usable:
            return None

        weights: dict[str, float] = {}
        for neighbour in usable:
            category_id = neighbour.get("category_id")
            if not category_id:
                continue
            weights[category_id] = weights.get(category_id, 0.0) + float(
                neighbour["similarity"]
            )
        if not weights:
            return None

        total = sum(weights.values())
        winner, winning_weight = max(weights.items(), key=lambda pair: pair[1])
        share = winning_weight / total

        supporting = [n for n in usable if n.get("category_id") == winner]
        mean_similarity = sum(float(n["similarity"]) for n in supporting) / len(
            supporting
        )

        # Agreement alone is not enough: five weak matches that agree are
        # still weak evidence, so the share is scaled by how close they were.
        confidence = round(min(0.95, share * min(1.0, mean_similarity * 1.4)), 3)

        return Completion(
            text=json.dumps(
                {
                    "category_id": winner,
                    "description": user.strip(),
                    "urgency": "MEDIUM",
                    "severity": 0.5,
                    "urgency_score": 0.5,
                    "affected_population_estimate": 0,
                    "missing_details": [],
                    "confidence": confidence,
                    "rationale": (
                        f"{len(supporting)} of {len(usable)} similar past cases from "
                        f"this district were filed under {winner} "
                        f"(mean similarity {mean_similarity:.2f})."
                    ),
                }
            ),
            model=self.name,
            confidence=confidence,
        )

    def complete_json(
        self, *, system: str, user: str, schema_hint: str, context: dict[str, Any]
    ) -> Completion:
        voted = self._vote(context.get("neighbours") or [], user)
        if voted is not None:
            return voted

        categories: Sequence[dict[str, Any]] = context.get("categories") or []
        tokens = set(tokenize(user))

        scored: list[tuple[float, dict[str, Any]]] = []
        for category in categories:
            vocabulary = set(
                tokenize(f"{category['category']} {category['subcategory']}")
            )
            if not vocabulary:
                continue
            overlap = len(tokens & vocabulary)
            scored.append((overlap / len(vocabulary), category))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        if not scored or scored[0][0] == 0:
            return Completion(
                text=json.dumps(
                    {
                        "category_id": None,
                        "description": user.strip(),
                        "urgency": "MEDIUM",
                        "missing_details": ["category could not be determined"],
                        "confidence": 0.0,
                        "rationale": (
                            "Offline classifier found no wording overlap with any "
                            "category in the loaded master."
                        ),
                    }
                ),
                model=self.name,
                confidence=0.0,
            )

        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        confidence = round(min(0.95, best_score + (best_score - runner_up)), 3)

        return Completion(
            text=json.dumps(
                {
                    "category_id": best["category_id"],
                    "description": user.strip(),
                    "urgency": best.get("default_priority", "MEDIUM"),
                    "missing_details": [],
                    "confidence": confidence,
                    "rationale": (
                        f"Offline classifier matched the complaint wording to "
                        f"{best['category']} / {best['subcategory']}."
                    ),
                }
            ),
            model=self.name,
            confidence=confidence,
        )


# --------------------------------------------------------------------------
# OpenAI provider
# --------------------------------------------------------------------------


class OpenAIProvider:
    """Thin wrapper over the chat completions API returning JSON."""

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key)
        self.name = model or settings.chat_model

    def complete_json(
        self, *, system: str, user: str, schema_hint: str, context: dict[str, Any]
    ) -> Completion:
        payload = {
            "complaint": user,
            "allowed_categories": context.get("categories", []),
            # How this district has classified similar complaints before.
            # Reference for the category choice only; it carries no policy and
            # no outcome, and the model is told so in the system prompt.
            "similar_past_cases_for_reference": context.get("neighbours", []),
            "required_output": schema_hint,
        }
        response = self._client.chat.completions.create(
            model=self.name,
            response_format={"type": "json_object"},
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        )
        text = response.choices[0].message.content or "{}"
        try:
            confidence = float(json.loads(text).get("confidence", 0.0))
        except (json.JSONDecodeError, TypeError, ValueError):
            confidence = 0.0
        return Completion(
            text=text,
            model=self.name,
            confidence=max(0.0, min(1.0, confidence)),
        )


def get_provider() -> LLMProvider:
    """Return the configured provider, falling back to the offline stub."""
    if settings.openai_api_key:
        return OpenAIProvider()
    return StubProvider()
