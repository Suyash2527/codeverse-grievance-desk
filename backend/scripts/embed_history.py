"""Generate embeddings for the historical cases.

    python scripts/embed_history.py

Uses the configured OpenAI embedding model when OPENAI_API_KEY is set, and a
deterministic offline embedding otherwise. Re-running only embeds rows that
are missing one, unless --all is passed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import GrievanceHistory  # noqa: E402
from app.rag.embeddings import embed_texts, embedding_method  # noqa: E402

BATCH = 100


def main(argv: list[str]) -> int:
    redo_all = "--all" in argv
    init_db()
    print(f"method   : {embedding_method()}")

    with SessionLocal() as session:
        stmt = select(GrievanceHistory)
        if not redo_all:
            stmt = stmt.where(GrievanceHistory.embedding.is_(None))
        rows = list(session.scalars(stmt))
        if not rows:
            print("nothing to embed; all history rows already have an embedding")
            return 0

        print(f"embedding: {len(rows)} row(s) in batches of {BATCH}")
        for start in range(0, len(rows), BATCH):
            batch = rows[start : start + BATCH]
            vectors = embed_texts([r.complaint_text for r in batch])
            for row, vector in zip(batch, vectors):
                row.embedding = vector
            session.commit()
            print(f"  {min(start + BATCH, len(rows))}/{len(rows)}")

    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
