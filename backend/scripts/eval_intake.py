"""Measure how well intake classifies complaints it has never seen.

    python scripts/eval_intake.py [--sample 200]

Leave-one-out evaluation over the historical cases: each sampled complaint is
classified while that same row is excluded from the evidence, and the
predicted category is compared with the recorded one.

Why this matters: judges test fresh, unseen scenarios. The offline path has to
be good enough that a demo without an API key is still a working demo, and the
only honest way to know is to measure it.
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.agents.intake import category_catalogue, neighbour_evidence  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.llm.provider import StubProvider  # noqa: E402
from app.models import GrievanceHistory  # noqa: E402


NOVEL_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "novel_complaints.json"
)


def evaluate_novel() -> int:
    """Measure on hand-written complaints in wording absent from the history.

    Leave-one-out over the supplied history flatters the classifier badly:
    that history is templated, so every held-out row still has near-duplicates
    of its own category in the index. This set is the honest estimate of what
    happens when a judge types something new.
    """
    import json

    payload = json.loads(NOVEL_FIXTURE.read_text(encoding="utf-8"))
    complaints = payload["complaints"]

    with SessionLocal() as session:
        catalogue = category_catalogue(session)
        provider = StubProvider()

        exact = 0
        acceptable = 0
        misses: list[tuple[str, str, str, float]] = []
        confidences: list[float] = []

        for item in complaints:
            evidence = neighbour_evidence(session, item["text"])
            answer = provider.complete_json(
                system="",
                user=item["text"],
                schema_hint="",
                context={"categories": catalogue, "neighbours": evidence},
            ).as_json()
            predicted = answer.get("category_id")
            confidence = float(answer.get("confidence") or 0.0)
            confidences.append(confidence)

            if predicted == item["expected"]:
                exact += 1
            elif predicted in item["acceptable"]:
                acceptable += 1
            else:
                misses.append(
                    (item["text"][:64], item["expected"], str(predicted), confidence)
                )

    total = len(complaints)
    print(f"novel complaints : {total} (wording absent from the history)")
    print(f"exact category   : {exact}/{total} = {exact / total:.1%}")
    print(f"acceptable       : {(exact + acceptable)}/{total} = {(exact + acceptable) / total:.1%}")
    print(f"mean confidence  : {sum(confidences) / total:.3f}")
    routed = sum(1 for c in confidences if c < 0.75)
    print(
        f"below threshold  : {routed}/{total} = {routed / total:.1%} "
        f"(routed to a human instead of auto-resolved)"
    )
    if misses:
        print("\nmisses:")
        for text, expected, predicted, confidence in misses:
            print(f"  {text}...")
            print(f"    expected {expected} / predicted {predicted} @ {confidence}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--novel",
        action="store_true",
        help="evaluate on hand-written unseen complaints instead of history",
    )
    args = parser.parse_args(argv)

    if args.novel:
        init_db()
        return evaluate_novel()

    init_db()
    random.seed(args.seed)

    with SessionLocal() as session:
        rows = list(session.scalars(select(GrievanceHistory)))
        if not rows:
            print("no history loaded; run scripts/load_data.py first")
            return 1
        embedded = sum(1 for row in rows if row.embedding)
        if embedded == 0:
            print(
                "history has no embeddings; run scripts/embed_history.py first "
                "(the keyword fallback will be measured instead)"
            )

        sample = random.sample(rows, min(args.sample, len(rows)))
        catalogue = category_catalogue(session)
        provider = StubProvider()

        results: Counter[str] = Counter()
        confidences: list[float] = []
        wrong_examples: list[tuple[str, str, str]] = []

        for row in sample:
            evidence = neighbour_evidence(
                session, row.complaint_text, exclude_ids={row.grievance_id}
            )
            answer = provider.complete_json(
                system="",
                user=row.complaint_text,
                schema_hint="",
                context={"categories": catalogue, "neighbours": evidence},
            ).as_json()

            predicted = answer.get("category_id")
            confidence = float(answer.get("confidence") or 0.0)
            confidences.append(confidence)

            if predicted == row.category_id:
                results["exact"] += 1
            else:
                predicted_row = next(
                    (c for c in catalogue if c["category_id"] == predicted), None
                )
                actual_row = next(
                    (c for c in catalogue if c["category_id"] == row.category_id), None
                )
                if (
                    predicted_row
                    and actual_row
                    and predicted_row["category"] == actual_row["category"]
                ):
                    results["same_department_family"] += 1
                else:
                    results["wrong"] += 1
                    if len(wrong_examples) < 5:
                        wrong_examples.append(
                            (row.complaint_text[:70], row.category_id, str(predicted))
                        )

    total = len(sample)
    exact = results["exact"]
    family = results["same_department_family"]

    print(f"sample          : {total} complaints, leave-one-out")
    print(f"embedded rows   : {embedded}/{len(rows)}")
    print()
    print(f"exact category  : {exact}/{total} = {exact / total:.1%}")
    print(f"right family    : {family}/{total} = {family / total:.1%}")
    print(f"combined        : {(exact + family) / total:.1%}")
    print(f"wrong           : {results['wrong']}/{total} = {results['wrong'] / total:.1%}")
    print()
    print(f"mean confidence : {sum(confidences) / len(confidences):.3f}")
    below = sum(1 for c in confidences if c < 0.75)
    print(
        f"below threshold : {below}/{total} = {below / total:.1%} "
        f"(these route to a human rather than auto-resolving)"
    )

    if wrong_examples:
        print("\nmisclassified examples:")
        for text, actual, predicted in wrong_examples:
            print(f"  {text}...")
            print(f"    actual {actual} / predicted {predicted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
