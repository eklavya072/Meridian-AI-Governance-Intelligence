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
| **Analysis latency** — upload accepted to brief available | p95 < 15 min | **78.9 s**, one live run on a healthy provider (2026-09-30, `docs/MEASUREMENTS.md`); no p95 yet | A full run is about ten LLM calls; the three that matter took 20s, 38s and 28s when the model answered, so the floor is set by the provider, not by us. |
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

**Response.** Lower `ANALYSIS_MAX_CONCURRENCY` (default 3; each worker holds
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
`sha-<full-commit-sha>`. **Deploy and roll back by SHA tag, never by
`latest`** — `latest` is exactly the tag that just moved.

```bash
# What is running now
docker inspect --format '{{.Config.Image}}' $(docker compose -f docker-compose.prod.yml --env-file .env.prod ps -q api)

# Deploy a release, or roll back to one: the same command
make rollout IMAGE_REF=ghcr.io/eklavya072/meridian:sha-<commit>
```

`deploy/rollout.sh` starts the new image beside the running one, waits for
its `/readyz` (Postgres, the vector store and provider capacity), then drains
and removes the old container. If the new one never becomes ready it is
removed and the old one keeps serving: a failed rollout changes nothing. It
needs the Chroma server (`--profile scale`, `CHROMA_HOST=chroma` in
`.env.prod`), because two containers must never open one embedded index.

**Measured** (`docs/MEASUREMENTS.md`, three drill runs on a GitHub runner,
images pre-pulled): a rollout or rollback takes 8.8–9.4 s, the new container
is ready after 7.2–7.3 s, and 0 of 921 probes through the proxy failed. A
cold pull of the image adds its download time.

---

## Secrets and key rotation

**Where secrets live.** `GEMINI_API_KEY`, `ADMIN_TOKEN` and
`POSTGRES_PASSWORD` are read from `.env` (development), `.env.prod`
(production) or the host's secret store (on Hugging Face, Space secrets).
All three files are git-ignored. CI never holds a real key: the smoke tests
start the image with a placeholder, and nothing in startup or either probe
calls the provider.

**Verified absent from history** (2026-09-30): no `.env`, `.env.prod` or
`backend/.env` has ever been committed, and no commit diff contains a
Google API key or Hugging Face token pattern. Re-check before any release:

```bash
git log --all --format=%h -- .env .env.prod backend/.env
git log --all -p | grep -E "AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z]{30,}"
```

Both must print nothing.

**Rotating the Gemini key** — on a schedule, and immediately if a key may
have been exposed:

1. Create the new key in Google AI Studio. Keep the old one live for now.
2. Replace `GEMINI_API_KEY` where it is set (`.env.prod`, or the Space
   secret).
3. Restart the API: `docker compose -f docker-compose.prod.yml up -d --no-deps api`
   (the Space restarts itself when a secret changes).
4. Gate on readiness: `make ready`. `/readyz` reports the provider check,
   and the next analysis or chat logs `llm_request_ok`.
5. Revoke the old key in AI Studio.
6. **Reset the credential's ledger entry if the old key was circuit-open or
   out of daily budget.** The key registry labels a credential by position
   (`geminiprovider:0`), not by value, so the new key inherits the old one's
   record. Delete `data/provider_health.json`, or today's row in the
   `provider_health` table (one row per day, holding every credential's
   state) when `PROVIDER_HEALTH_DSN` is set.

A key that was ever committed is compromised however quickly it was removed:
rotate it, do not rewrite history and hope.

---

## Known limits

Stated because a runbook that omits them is worse than none.

- **No durable queue.** Analysis runs in-process. A restart loses in-flight
  work; the startup sweep makes that recoverable, not invisible.
- **Backpressure is per process.** A workspace refuses a second run (409), and
  `MAX_CONCURRENT_ANALYSES` (default 2) refuses runs beyond it with 429 rather
  than queueing them. The limit counts one process, not a cluster.
- **`GEMINI_RPD_LIMIT` is our own accounting**, not a reading of Google's
  quota, and it is off by default. The authoritative limit is the provider's
  refusal, which the key registry records per credential.
- **There is no fallback provider.** Gemini is the only one. A 503 is answered
  by waiting the delay the API asks for, across `PROVIDER_MAX_RETRIES`
  attempts. If a run reports failed dimensions, lower
  `ANALYSIS_MAX_CONCURRENCY` and re-run — the pipeline reuses the dimensions
  that already succeeded, so a retry only redoes the failures.
- **Replicas need two variables, and nothing else.** Postgres and uploads
  (Azure Blob backend) were already shared. The two that were not:

      CHROMA_HOST=chroma            # index behind a server, not a local dir
      PROVIDER_HEALTH_DSN=postgres… # one quota ledger, not one per replica

  `docker compose --profile scale up -d --scale api=3` starts the Chroma
  service and runs three API containers. Unset, both default to the embedded
  single-instance behaviour and every existing data directory keeps working.

  **What is still process-local, and what it costs.** Admission slots
  (`get_slots()`) are per replica, so the in-flight cap is per replica rather
  than per cluster — N replicas admit N times the work. The RPM throttle is
  per replica too, so the pool can exceed a per-minute limit under load; the
  per-DAY ledger is shared, which is the limit that actually ends a run.
  Neither is a correctness bug, but do not describe the deployment as
  horizontally scalable without saying which limits are still per process.
