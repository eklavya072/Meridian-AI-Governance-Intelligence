# Measurements

Every number in this file comes from a run recorded here, with the hardware,
model versions and date beside it. Nothing is estimated. Where something has
not been measured yet, it says `not measured` rather than carrying a
plausible-looking placeholder.

## Environment

| | |
|---|---|
| Machine | Apple MacBook Air, M2, 8 GB RAM, macOS 14.6 (Darwin 23.6.0) |
| Python | 3.13.9 |
| Embedding model | `BAAI/bge-small-en-v1.5` (384-dim) |
| NLI model | `cross-encoder/nli-deberta-v3-base` |
| Vector store | ChromaDB 1.5.9, local persistent |
| Database | PostgreSQL 16 |

---

## Citation verification: embedding vs NLI

**Date:** 2026-08-30 · **Gemini calls:** 0 (reads stored analyses, Chroma and
local models only) · **Harness:** pulls every evidence item from the 11 stored
analyses, resolves the chunk each one cites, and scores the pair three ways.

### Dataset

| | |
|---|---|
| Stored analyses | 11 (EU ×4, Japan ×2, India ×2, Kenya ×2, Egypt ×1) |
| Evidence items | 471 |
| Resolved against the live index | 403 |
| Unresolvable (orphaned chunk ids) | 68 |

The 68 orphans predate `_deterministic_chunk_id()`: they were minted as
`uuid4` and re-ingestion gave the same text a new id. They are the residue of
a fixed bug, not a live one.

### What is actually being verified

`verify_gap_analysis_citations` passes `claim_text=text[:200]`, where `text`
is the excerpt the model quoted. So the check is *"is this quoted excerpt
consistent with the chunk it was drawn from"* — it catches fabricated quotes
and mis-attributed chunk ids. It is not an entailment check between an
analytical claim and its evidence, and the README no longer says it is.

**344 of 403 (85.4%)** quoted excerpts appear verbatim in the chunk they cite,
after collapsing whitespace (PDF extraction breaks words: `T ransparency`,
`Ar ticle`). For those, fabrication is impossible by construction.

### Results

| | Embedding (`bge-small`, cosine ≥ 0.65) | NLI (`nli-deberta-v3-base`) |
|---|---|---|
| Accepts | **363 / 403 (90.1%)** | 124 / 403 (30.8%) |
| Accepts, of the 344 verbatim-contained | **305 / 344 (88.7%)** | 100 / 344 (29.1%) |
| Latency per pair | 28.2 ms (2 embeds) | 86.7 ms |
| Cosine mean / median | 0.766 / 0.758 | — |
| Cosine min / max | 0.494 / 0.969 | — |

Agreement between the two paths: **164 / 403 (40.7%)**. Embedding accepts and
NLI rejects: **239**. NLI accepts and embedding rejects: **0**.

### Two bugs found along the way

Running the NLI path for the first time returned **362 of 403 (89.8%) labelled
"contradicts"** — on a set where 85% of excerpts are copied verbatim out of the
chunk they cite. An excerpt cannot contradict its own source, so the verifier,
not the data, was wrong. Two independent causes:

1. **Inverted label order.** `_verify_nli` read scores positionally as
   `[entailment, neutral, contradiction]`. The checkpoint reports
   `{0: contradiction, 1: entailment, 2: neutral}`, so contradiction was read
   as entailment and neutral as contradiction.
2. **Logits compared against probability thresholds.** `CrossEncoder.predict`
   returns raw logits for a multi-class head (observed roughly −6 to +6),
   compared directly against the 0.6 / 0.4 thresholds. A logit of `5.84` for
   *neutral* cleared a 0.4 "contradiction" bar purely by being a large number.

Both are silent: nothing raises, nothing logs, and the output still looks like
scores. Fixed by reading `id2label` from the checkpoint and applying softmax.
Contradictions fell from **362 to 14**. `tests/unit/test_nli_label_order.py`
pins both, including that a dominant *neutral* is never reported as a
contradiction.

Because the flag defaults to off, this never affected a shipped analysis. It
would have destroyed one the moment anyone switched it on.

### Decision

**The embedding path stays the default.** Even with both bugs fixed, NLI
rejects 71% of excerpts that are verbatim copies of their own source — false
negatives, not caught fabrications. A general-purpose MNLI checkpoint is
being asked to judge 512-character statutory fragments with OCR damage, which
is not the task it was trained for. It stays available behind
`ENABLE_NLI_VERIFICATION=true`, now correct if enabled.

Worth revisiting only with a checkpoint suited to legal text, and only against
this same dataset.

---

## Container image

**Date:** 2026-08-30 · Measured in CI on `ubuntu-latest`, `linux/amd64`.

| | Size |
|---|---|
| Before | **5,683 MB** |
| After removing the CUDA stack | **1,869 MB** (−67%) |

torch's default PyPI wheel bundles the NVIDIA CUDA runtime — 43 `nvidia-*`
packages, one of them a single 542 MB wheel. Meridian runs `bge-small` on CPU
and has no GPU code path, so Linux now resolves torch from PyTorch's CPU
index. macOS stays on PyPI, whose darwin wheels are already CPU-only.

Remaining size is dominated by torch itself (~500 MB CPU), plus
`sentence-transformers`, `chromadb` and the ~130 MB baked-in embedding model.
The model is deliberate: startup otherwise makes a network call to
huggingface.co before it can serve, and a DNS failure during one has already
taken this API down.

---

## Vulnerability scan

**Date:** 2026-08-30 · `trivy` in the release pipeline, scanning the built
`prod` image before it is pushed.

### Baseline — first scan

| Severity | Count |
|---|---|
| CRITICAL | 3 |
| HIGH | 16 |
| MEDIUM | 60 |
| LOW | 75 |
| UNKNOWN | 7 |
| **Total** | **161** |

The gate covers HIGH/CRITICAL **with a fix available** (`--ignore-unfixed`).
Three qualified, and the gate blocked the push while the image was still
private — which is the reason the scan runs before the push rather than after.

### What was fixed, and how

All three were fixed at source. **`.trivyignore` is empty** — nothing has been
allowlisted.

| Package | Advisory | Resolution |
|---|---|---|
| `openssl` / `libssl3t64` 3.5.6-1~deb13u2 | CVE-2026-14456 (HIGH) | The base image tag lags the Debian security archive. The base stage now runs `apt-get upgrade`, pulling 3.5.7-1~deb13u2. |
| `setuptools` 70.3.0 | CVE-2025-47273 (HIGH) | Not a Meridian dependency — vendored inside the base image's `pip`. Our locked setuptools is 84.0.0. |
| `msgpack` 1.1.2 | GHSA-6v7p-g79w-8964 (HIGH) | Also vendored inside `pip`; nothing in the project depends on msgpack. |

The last two were resolved together by removing `pip` from the production
stage. The application runs entirely from `/opt/venv` and never invokes the
system installer, so a package manager in a production image was surface with
no purpose.

The remaining CRITICAL/HIGH findings have no fix available upstream
(`chromadb` CVE-2026-45829, `perl-base` CVE-2026-13221, `ncurses`
CVE-2025-69720 and others). They are reported and tracked in the Security tab
via SARIF, and are not suppressed — `--ignore-unfixed` means the gate does not
fail on something this repository cannot act on, which is a different thing
from pretending it is not there.

---

## Test suite

**Date:** 2026-08-30 · Measured on the environment above, against a clean
`uv sync --frozen` rather than the development virtualenv.

| | |
|---|---|
| Result | 721 passed, 9 skipped |
| Wall clock | ~10 s |
| Coverage (`src`) | **60%** (8,619 statements, 3,485 missed) |

The 9 skips are deliberate: 5 evaluation tests behind `RUN_EVALUATION_TESTS=1`
(they need an indexed corpus), 3 integration tests behind
`RUN_INTEGRATION_TESTS=1`, and 1 needing a PDF with a real text layer.

Lowest-covered modules, honestly: `tasks.py` 0%, `workspace.py` 0%,
`chat.py` 10%, `governance_advisor.py` 17%, `llm_provider.py` 24%,
`provider_router.py` 26%. The CI gate is set at **58%** — just below measured,
so it catches regression without being aspirational.

---

## Not yet measured

- End-to-end analysis latency (p50/p95/p99), throughput, error rate, peak memory
- Live vs replay pipeline cost
- Container image size and cold-start time
- Vulnerability counts before and after remediation
