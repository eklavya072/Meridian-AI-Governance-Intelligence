"""Measure what citation verification actually does, on real stored citations.

Pulls every evidence item from every stored analysis, fetches the chunk it
cites, and characterises the claim/chunk pair two ways:

  containment  — is the quoted excerpt literally inside the chunk text
  embedding    — bge-small cosine, the check that runs in the pipeline

Run it after changing a threshold or the chunker, to see what moved before
trusting it. `make bench`.

No Gemini calls: this reads Postgres, Chroma and local models only.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import sys
import time

# scripts/ is on the path when run as `python scripts/measure_verification.py`;
# backend/ is what `src` imports need, and where the index lives.
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("CHROMA_PERSIST_DIR", str(BACKEND_DIR / "data" / "chroma"))

import psycopg2  # noqa: E402

DSN = os.getenv("MEASURE_DSN", "postgresql://aura:aura@localhost:5432/aura_sdg")


def normalise(s: str) -> str:
    """PDF extraction breaks words ("Ar ticle", "T ransparency"), so a literal
    containment test has to collapse whitespace before comparing."""
    return re.sub(r"\s+", "", s).lower()


def load_pairs() -> list[dict]:
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("select id, document_name, governance_gaps from analyses order by created_at")
    pairs = []
    for analysis_id, doc, gaps in cur.fetchall():
        if isinstance(gaps, str):
            gaps = json.loads(gaps)
        for gap in gaps or []:
            for ev in gap.get("evidence", []) or []:
                if not ev.get("chunk_id") or not ev.get("text"):
                    continue
                pairs.append(
                    {
                        "analysis_id": str(analysis_id),
                        "document": doc,
                        "dimension": gap.get("dimension"),
                        "chunk_id": ev["chunk_id"],
                        "claim": ev["text"][:200],
                        "stored_verified": ev.get("verified"),
                        "stored_sim": (ev.get("verification") or {}).get("semantic_similarity"),
                    }
                )
    cur.close()
    conn.close()
    return pairs


def main() -> None:
    pairs = load_pairs()
    print(f"evidence items in stored analyses: {len(pairs)}")

    from src.vectorstore import VectorStore

    vs = VectorStore(persist_dir=os.environ["CHROMA_PERSIST_DIR"])

    resolved, missing = [], 0
    for p in pairs:
        chunk = vs.get_chunk(p["chunk_id"])
        if not chunk:
            missing += 1
            continue
        p["chunk_text"] = chunk["text"]
        resolved.append(p)

    print(f"resolved against the live index: {len(resolved)}  (missing: {missing})")
    if not resolved:
        return

    # ── containment ────────────────────────────────────────────────────
    contained = sum(1 for p in resolved if normalise(p["claim"]) in normalise(p["chunk_text"]))
    print(
        f"\nquoted excerpt is literally inside its cited chunk: "
        f"{contained}/{len(resolved)} ({contained / len(resolved):.1%})"
    )

    # ── embedding path (what runs today) ───────────────────────────────
    from src.utils import cosine_similarity

    t0 = time.time()
    sims = []
    for p in resolved:
        a = vs.embedding_service.embed_query(p["claim"][:500])
        b = vs.embedding_service.embed_query(p["chunk_text"][:500])
        sims.append(cosine_similarity(a, b))
        p["embed_sim"] = sims[-1]
    embed_secs = time.time() - t0

    THRESHOLD = float(os.getenv("SEMANTIC_VERIFICATION_THRESHOLD", "0.65"))
    embed_pass = sum(1 for s in sims if s >= THRESHOLD)
    print(f"\nembedding (bge-small, threshold {THRESHOLD}):")
    print(f"  passes            {embed_pass}/{len(sims)} ({embed_pass / len(sims):.1%})")
    print(f"  cosine mean/med   {statistics.mean(sims):.3f} / {statistics.median(sims):.3f}")
    print(f"  cosine min/max    {min(sims):.3f} / {max(sims):.3f}")
    print(
        f"  latency/pair      {embed_secs / len(resolved) * 1000:.1f} ms  "
        f"({embed_secs:.1f}s total, 2 embeds per pair)"
    )

    # The NLI verification path that used to be measured here is gone. It
    # was wired in, measured against a real Kenya run, and rejected: the
    # cross-encoder reads 512 tokens against chunks averaging 2,374
    # characters, so it marked 36 of 48 correct citations irrelevant. It
    # never changed a verdict — verification is a reporting layer — so the
    # only thing it moved was the reported citation rate, downwards. See
    # docs/MEASUREMENTS.md.


if __name__ == "__main__":
    main()
