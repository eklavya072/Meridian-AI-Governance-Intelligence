"""Sparse (BM25) retrieval fused with the dense vector sweep.

Dense embeddings summarise what a passage is ABOUT. Two passages about logging
land near each other whether one says "shall ensure automatic recording of
events" or "may consider retaining records" — and that distinction is the one
this instrument exists to draw, discarded before the classifier ever sees it.

BM25 has the complementary strength: it cannot tell "logging" from "record
keeping", but it matches EXACT tokens — "shall", "Article 14", "e-waste",
"conformity assessment" — and those are what a governance mechanism actually
looks like in a statute. A dense miss is unrecoverable downstream, because a
chunk that never reaches the prompt makes a retrieval failure and a genuine
absence indistinguishable.

Fusion is Reciprocal Rank Fusion (Cormack et al., SIGIR 2009):

    RRF(d) = SUM_r  1 / (k + rank_r(d))

RRF consumes only RANKS, so it needs no reconciliation between BM25 scores and
cosine similarities — which are not on a comparable scale, and any fixed
weighting between them would be a hyperparameter nobody can defend. k=60 is the
value from the original paper, deliberately left alone.

MEASURED EFFECT, so nobody has to guess: on Kenya this promotes 3-9 chunks per
dimension that the dense sweep had not ranked, and changed no verdict on Kenya,
Japan or the EU. It is kept for recall insurance on documents where the dense
sweep is weaker, not because it moved a number here.

BM25 is implemented here rather than taken from `rank_bm25` because the scoring
loop is thirty lines and the tokeniser has to be policy-aware — keeping
"e-waste" and "14(2)" intact, and NOT stoplisting "shall", "must" or "not",
which are the highest-information tokens in this corpus.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()

# Okapi BM25 defaults. Not tuned: tuning them against this corpus with no
# relevance judgements would be fitting to noise.
BM25_K1 = 1.5
BM25_B = 0.75

# RRF constant from Cormack et al. Damps the very top ranks so one retriever's
# confident mistake cannot dominate the fused list.
RRF_K = 60

# Deliberately SHORT. An aggressive stoplist removes "not", "shall" and "may",
# which carry more signal here than any content word.
_STOPWORDS = frozenset(
    """a an the of to in for on by with and or as at from that this these those
    is are was were be been being it its their there such which who whom whose
    any all each other than then when where while into upon per""".split()
)

# Keeps hyphenated compounds ("e-waste", "post-market") and division references
# ("14(2)") whole. A plain \w+ split shreds all three into fragments that match
# everything and discriminate nothing.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-–][a-z0-9]+)*(?:\(\d+\))?", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    toks = [t.lower() for t in _TOKEN_RE.findall(text or "")]
    return [t for t in toks if t not in _STOPWORDS and len(t) > 1]


@dataclass
class BM25Index:
    """In-memory BM25 over a chunk set.

    Built per retrieval scope rather than held globally: a workspace's chunk
    population changes between runs, and a stale index would silently retrieve
    provisions from a document the run does not include.
    """

    documents: list[dict[str, Any]] = field(default_factory=list)
    _tokens: list[list[str]] = field(default_factory=list, repr=False)
    _doc_freq: Counter = field(default_factory=Counter, repr=False)
    _doc_len: list[int] = field(default_factory=list, repr=False)
    _avg_len: float = 0.0

    @classmethod
    def build(cls, chunks: Sequence[dict[str, Any]], text_key: str = "text") -> BM25Index:
        idx = cls()
        for c in chunks:
            toks = tokenize(c.get(text_key, ""))
            idx.documents.append(c)
            idx._tokens.append(toks)
            idx._doc_len.append(len(toks))
            idx._doc_freq.update(set(toks))
        idx._avg_len = (sum(idx._doc_len) / len(idx._doc_len)) if idx._doc_len else 0.0
        return idx

    def __len__(self) -> int:
        return len(self.documents)

    def _idf(self, term: str) -> float:
        """Robertson/Sparck-Jones IDF with +1 smoothing.

        The unsmoothed form goes negative past 50% document frequency, so in a
        single-statute scope a common drafting word would actively subtract
        from a document's score.
        """
        n = len(self.documents)
        df = self._doc_freq.get(term, 0)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        """(document index, score), best first."""
        q_terms = tokenize(query)
        if not q_terms or not self.documents:
            return []
        scores: list[tuple[int, float]] = []
        for i, toks in enumerate(self._tokens):
            if not toks:
                continue
            tf = Counter(toks)
            dl = self._doc_len[i]
            s = 0.0
            for term in q_terms:
                f = tf.get(term, 0)
                if not f:
                    continue
                denom = f + BM25_K1 * (
                    1 - BM25_B + BM25_B * (dl / self._avg_len if self._avg_len else 1.0)
                )
                s += self._idf(term) * (f * (BM25_K1 + 1)) / denom
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    k: int = RRF_K,
    weights: Sequence[float] | None = None,
) -> dict[str, float]:
    """Fuse ranked id lists into one score map. Higher is better."""
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    fused: dict[str, float] = {}
    for lst, w in zip(ranked_lists, weights):
        for rank, doc_id in enumerate(lst, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return fused


def hybrid_search(
    query: str,
    dense_results: Sequence[dict[str, Any]],
    corpus: Sequence[dict[str, Any]],
    top_k: int = 30,
    id_key: str = "chunk_id",
    text_key: str = "text",
    sparse_top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Fuse an existing dense result list with a BM25 sweep over `corpus`.

    `corpus` is normally WIDER than `dense_results` — the whole workspace
    document set — so sparse retrieval can surface a passage the dense sweep
    never ranked at all. That asymmetry is the point: fused over the dense pool
    alone, BM25 could only re-order what dense already found and could never
    fix a dense MISS.

    Chunks carry `retrieval_sources` so a later audit can tell whether the
    sparse pass actually contributed. Without that the change is unfalsifiable.
    """
    sparse_top_k = sparse_top_k or max(top_k * 2, 50)

    by_id: dict[str, dict[str, Any]] = {}
    for c in corpus:
        cid = c.get(id_key)
        if cid:
            by_id[cid] = c
    for c in dense_results:
        cid = c.get(id_key)
        if cid and cid not in by_id:
            by_id[cid] = c

    dense_ids = [c.get(id_key) for c in dense_results if c.get(id_key)]

    index = BM25Index.build(corpus, text_key=text_key)
    sparse_ids = [
        index.documents[i].get(id_key)
        for i, _ in index.search(query, top_k=sparse_top_k)
        if index.documents[i].get(id_key)
    ]

    fused = reciprocal_rank_fusion([dense_ids, sparse_ids])
    dense_set, sparse_set = set(dense_ids), set(sparse_ids)

    out: list[dict[str, Any]] = []
    for cid, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]:
        chunk = by_id.get(cid)
        if chunk is None:
            continue
        enriched = dict(chunk)
        enriched["rrf_score"] = round(score, 6)
        sources = []
        if cid in dense_set:
            sources.append("dense")
        if cid in sparse_set:
            sources.append("bm25")
        enriched["retrieval_sources"] = sources
        out.append(enriched)

    logger.info(
        "hybrid_search",
        dense=len(dense_ids),
        sparse=len(sparse_ids),
        sparse_only=len(sparse_set - dense_set),
        returned=len(out),
    )
    return out


def sparse_only_recall(results: Iterable[dict[str, Any]]) -> int:
    """How many returned chunks BM25 found that the dense sweep did not — the
    number that says whether the sparse pass earned its cost on this query."""
    return sum(
        1
        for r in results
        if "bm25" in (r.get("retrieval_sources") or [])
        and "dense" not in (r.get("retrieval_sources") or [])
    )
