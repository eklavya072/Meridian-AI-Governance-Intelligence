"""Measure what citation verification actually does, on real stored citations.

Pulls every evidence item from the 11 stored analyses, fetches the chunk it
cites, and characterises the claim/chunk pair three ways:

  containment  — is the quoted excerpt literally inside the chunk text
  embedding    — bge-small cosine, the check that runs today
  nli          — deberta entailment, the check the README claims runs

No Gemini calls. Everything below reads Postgres, Chroma and local models.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, "/Users/ed/Tech Projects/Meridian/Meridian/backend")
os.environ.setdefault("CHROMA_PERSIST_DIR", "/Users/ed/Tech Projects/Meridian/Meridian/backend/data/chroma")

import psycopg2  # noqa: E402

DSN = "postgresql://aura:aura@localhost:5432/aura_sdg"


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
    print(f"\nquoted excerpt is literally inside its cited chunk: "
          f"{contained}/{len(resolved)} ({contained / len(resolved):.1%})")

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
    print(f"  latency/pair      {embed_secs / len(resolved) * 1000:.1f} ms  "
          f"({embed_secs:.1f}s total, 2 embeds per pair)")

    # ── NLI path (what the README claims) ──────────────────────────────
    if os.getenv("RUN_NLI", "1") != "1":
        return

    from sentence_transformers import CrossEncoder

    model_name = os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-base")
    t0 = time.time()
    model = CrossEncoder(model_name)
    load_secs = time.time() - t0
    print(f"\nNLI ({model_name}) loaded in {load_secs:.1f}s")

    from src.nli_verifier import _resolve_label_index, _softmax

    idx = _resolve_label_index(model)
    print(f"  label index       {idx}")

    # Premise first (the chunk is the evidence), hypothesis second.
    t0 = time.time()
    raw = model.predict([(p["chunk_text"][:512], p["claim"][:256]) for p in resolved])
    nli_secs = time.time() - t0
    scores = [_softmax([float(v) for v in row]) for row in raw]

    ENT = float(os.getenv("NLI_THRESHOLD_ENTAILMENT", "0.6"))
    CON = float(os.getenv("NLI_THRESHOLD_CONTRADICTION", "0.4"))

    def label(row):
        ent = row[idx["entailment"]]
        neu = row[idx["neutral"]]
        con = row[idx["contradiction"]]
        if ent >= ENT:
            return "supports", ent
        if con >= CON:
            return "contradicts", con
        if ent >= 0.3:
            return "partially_supports", ent
        return "irrelevant", max(ent, neu)

    labels = [label(r) for r in scores]
    from collections import Counter

    dist = Counter(l for l, _ in labels)
    # verify.py counts SUPPORTS and PARTIALLY_SUPPORTS as passing.
    nli_pass = dist["supports"] + dist["partially_supports"]
    print(f"  passes            {nli_pass}/{len(labels)} ({nli_pass / len(labels):.1%})")
    print(f"  distribution      {dict(dist)}")
    print(f"  latency/pair      {nli_secs / len(resolved) * 1000:.1f} ms  ({nli_secs:.1f}s total)")

    agree = sum(
        1
        for p, (lab, _) in zip(resolved, labels)
        if (p["embed_sim"] >= THRESHOLD) == (lab in ("supports", "partially_supports"))
    )
    print(f"\nagreement between the two paths: {agree}/{len(resolved)} ({agree / len(resolved):.1%})")

    only_embed = [
        p for p, (lab, _) in zip(resolved, labels)
        if p["embed_sim"] >= THRESHOLD and lab not in ("supports", "partially_supports")
    ]
    only_nli = [
        p for p, (lab, _) in zip(resolved, labels)
        if p["embed_sim"] < THRESHOLD and lab in ("supports", "partially_supports")
    ]
    print(f"  embedding passes, NLI does not: {len(only_embed)}")
    print(f"  NLI passes, embedding does not: {len(only_nli)}")

    # The decisive slice: pairs where the quoted excerpt is LITERALLY inside
    # the chunk it cites. Nothing here can be a fabrication, so a verifier
    # rejecting these is producing false negatives, not catching anything.
    inside = [
        (p, lab)
        for p, (lab, _) in zip(resolved, labels)
        if normalise(p["claim"]) in normalise(p["chunk_text"])
    ]
    e_ok = sum(1 for p, _ in inside if p["embed_sim"] >= THRESHOLD)
    n_ok = sum(1 for _, lab in inside if lab in ("supports", "partially_supports"))
    print(f"\non the {len(inside)} verbatim-contained excerpts:")
    print(f"  embedding accepts {e_ok}/{len(inside)} ({e_ok / len(inside):.1%})")
    print(f"  NLI accepts       {n_ok}/{len(inside)} ({n_ok / len(inside):.1%})")


if __name__ == "__main__":
    main()
