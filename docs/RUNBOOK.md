# Runbook

Operating Meridian: what it promises, how it fails, and what to do about it.

Everything here is either a **target** (what we aim for) or a **measured**
value (what a recorded run produced). The two are labelled separately and
never merged. There are no production performance numbers in this document,
because Meridian has never run in production.

---

## Service objectives

Four objectives, deliberately few. Each is measurable from the metrics the
service already exposes at `/metrics`, so none of them depends on someone
remembering to record something.

| Objective | Target | Measured | Why this number |
|---|---|---|---|
| **Availability** — `/healthz` returns 200 | 99% monthly | *not measured — no production deployment* | A single-instance service with an in-process worker cannot honestly promise more. Three nines would require the queue and the redundancy described under "Known limits". |
| **Successful-analysis rate** — runs reaching `COMPLETE` with no failed dimension | ≥ 95% of runs | *not measured* | The dominant failure is provider quota, which is outside our control. 95% admits the occasional exhausted budget without excusing a code defect. |
| **Analysis latency** — upload accepted to brief available | p95 < 15 min | *not measured* | A full run is up to 16 LLM calls paced against a ~10 RPM per-credential ceiling, so the floor is set by the provider, not by us. |
| **Citation pass rate** — citations that resolve and verify | ≥ 85%, alert below 80% | **88.7%** on 344 verbatim-contained excerpts (2026-08-30, `docs/MEASUREMENTS.md`) | This is the only objective measured against real data, and it is the one that matters most: it is the evidence gate's own pass rate. |

The citation pass rate is the objective to watch. Availability and latency
degrade visibly; a quiet drop in citation quality does not, and it is the
one that would put an indefensible brief in front of a policy analyst.

---

## Failure modes

Each carries a detection signal, a diagnosis step, a response, and what
recovery looks like. The signals are real metric names and real log events,
not descriptions of signals we might add.

### 1. All provider credentials exhausted

**Detection.** `/readyz` returns 503 with
`checks.llm_provider.credentials_healthy: 0`. `meridian_provider_keys_healthy`
hits 0; `meridian_provider_failover_total{event="capacity_exhausted"}` rises.

**Diagnosis.** Read `/readyz`. `has_headroom: false` means the daily budget
is spent and it resets tomorrow. `has_headroom: true` with
`credentials_healthy: 0` means the circuit breaker has dropped every
credential — a rate-limit storm, not a spent budget, and it recovers on a
timer.

**Response.** Nothing, in the sense that no intervention helps. The service
already degrades correctly: `CapacityExhausted` names how long until a
credential is expected back, in-flight dimension results are persisted, and
a re-run resumes from them rather than re-spending quota on dimensions that
already succeeded. Stop new runs until `/readyz` reports 200.

**Recovery.** A credential returns to rotation automatically after its
cooldown, via a single probe. `GEMINI_RPD_LIMIT` reflects our own accounting,
not Google's — see "Known limits".

### 2. Provider outage or a retired model

**Detection.** `meridian_provider_requests_total{outcome="terminal"}` rises
from zero. Log event `provider_terminal_failure` with the credential id.

**Diagnosis.** A terminal failure is *not* a capacity problem. The classifier
separates them precisely so this is distinguishable: `404 model not found`
means `GEMINI_MODEL` names a model that no longer exists, and
`API key not valid` means the credential is wrong. Neither is fixed by
waiting, and neither rotates through the remaining credentials.

**Response.** Correct `GEMINI_MODEL` or the credential in the environment and
restart. If the provider itself is down, `outcome="retryable"` rises instead
and backoff handles it.

**Recovery.** Immediate on restart. Runs interrupted mid-flight are reclaimed
by the startup sweep (failure mode 5).

### 3. Chroma index corrupted

**Detection.** `/readyz` returns 503 with `checks.vector_store.ok: false`. In
the worst case the process dies with **no traceback at all** — a SIGSEGV
inside `chromadb_rust_bindings`, not a Python exception.

**Diagnosis.** This has happened here. The signal is not in the application
log: on macOS it is in `~/Library/Logs/DiagnosticReports/*.ips` under
`termination`; on Linux, `dmesg` or the container exit code (139 = SIGSEGV).
Reproduce with a bare `collection.count()`. Critically, memory pressure is a
plausible-looking red herring — the process died at 307 MB RSS with swap to
spare while the real cause was a torn HNSW segment written during an earlier
crash.

**Response.** Move the HNSW segment directory aside — do not delete it, keep
it as `data/chroma_hnsw_corrupt_<timestamp>` for forensics. Chroma rebuilds
the index from the embeddings still in SQLite. Verify on a copy first:
`count()` should return every embedding and a vector query should come back
in well under a second with sensible neighbours.

**Recovery.** Rebuild is minutes, not hours. SQLite is usually intact —
`integrity_check` passed in the recorded incident with all 47,365 embeddings
present.

### 4. Out of memory on a large document

**Detection.** Container exit code 137. `meridian_stage_duration_seconds`
shows `ingest` climbing before the process disappears.

**Diagnosis.** Check the page count and file size in
`stage_2_document_parsed`. Uploads are capped at 25 MB and 1,500 pages and
are read in bounded chunks, so a legitimate upload should not reach here — if
one does, the cap is wrong for the corpus rather than the file being hostile.

**Response.** Lower `ANALYSIS_MAX_CONCURRENCY` (default 8; each worker holds
its own retrieval context) and set `WARM_FRAMEWORK_COUNTS=0`, which skips a
startup sweep that holds the whole collection in memory.

**Recovery.** Restart. The startup sweep reclaims the wedged workspace.

### 5. Queue saturation / a wedged workspace

**Detection.** A workspace sits in `PROCESSING` with no progress.
`meridian_analysis_runs_total` stops rising while requests continue.

**Diagnosis.** The analysis worker runs **in-process** via FastAPI
`BackgroundTasks`. Nothing mid-run survives a restart, and the run endpoint
refuses to start a second analysis for a workspace already `PROCESSING` — so
a crash used to wedge it permanently. Two workspaces were stuck this way
once, one for nine hours.

**Response.** None needed: a row in a live state at startup is orphaned by
definition, and the startup sweep resets `PROCESSING → QUEUED` (re-runnable)
and `GENERATING_REPORT → COMPLETE` (the analysis finished; only the brief was
lost). `test_orphan_recovery.py` pins both, including the upper-case enum
labels — Postgres stores the member *names*, and a wrong-case sweep fails
into a warning and silently no-ops.

**Recovery.** Automatic on restart. Re-run the workspace.

---

## Deployment and rollback

Every image is published to GHCR tagged both `latest` and
`sha-<full-commit-sha>`. **Roll back by digest or by SHA tag, never by
`latest`** — `latest` is exactly the tag that just moved.

```bash
# What is running now
docker inspect --format '{{index .Config.Image}}' meridian-api

# Roll back to a known-good commit
docker pull ghcr.io/eklavya072/meridian:sha-<known-good-sha>
docker tag  ghcr.io/eklavya072/meridian:sha-<known-good-sha> meridian:rollback
docker compose -f docker-compose.prod.yml up -d --no-deps api

# Gate on readiness, not on the container being up
make ready
```

`make ready` polls `/readyz`, which checks Postgres, the vector store and
provider capacity. A container that is running but cannot serve is not a
successful deploy, and `/healthz` alone would call it one.

**A rollback has not yet been performed and timed.** It is written here as a
procedure, not reported as an exercise.

---

## Known limits

Stated because a runbook that omits them is worse than none.

- **No durable queue.** Analysis runs in-process. A restart loses in-flight
  work; the startup sweep makes that recoverable, not invisible.
- **No backpressure.** Concurrent runs are bounded per workspace (409 on a
  second run) but not globally. N workspaces can start N pipelines.
- **`GEMINI_RPD_LIMIT` is our own accounting**, not a reading of Google's
  quota. It has been observed reading 146/1000 while every credential was
  already returning 429.
- **The Groq fallback cannot serve analysis.** Prompts run ~16k tokens
  against an 8,000 TPM organisation limit, so it returns 413 whenever it is
  actually needed. Treat it as absent.
- **Single instance.** Storage is now shared-ready (Azure Blob backend), but
  Chroma is embedded and local, so horizontal scaling needs that solved
  first.
