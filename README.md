[![CI](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/ci.yml)
[![Release](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/release.yml/badge.svg)](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/release.yml)

# Meridian — AI Governance Intelligence Workbench

A government analyst uploads a national AI policy — a strategy, a framework, a
draft bill — and gets back a brief that says, dimension by dimension, what the
document actually commits to and what it leaves open. Every sentence in it
points at a specific passage of the document it came from, so a reader who
disagrees can go and check.

```bash
docker pull ghcr.io/eklavya072/meridian:latest
```

Public, no account needed, `linux/amd64` and `linux/arm64`. Or run the whole
stack — API, Postgres, frontend, Azurite — from a clean clone:

```bash
make up && make ready
```

**Live demo:** not yet deployed.

## Measured

Every number here comes from a recorded run; see
[docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) for the hardware, model versions
and dates. Anything unmeasured says so rather than carrying an estimate.

| | |
|---|---|
| Tests | **1,395 passed, 26 skipped**, including a replay gate over recorded Gemini answers and a golden set of two real instruments |
| Coverage (`src`) | **82%** — CI gate 80%, set from measurement |
| Production image | **1,889 MB** (down from 5,683 MB) |
| Vulnerabilities | **161 → 131** after remediation (3 fixable HIGH → 0) |
| Fixable HIGH/CRITICAL | **3 → 0**, all fixed at source; `.trivyignore` is empty |
| SBOM | 238 packages, SPDX 2.3, attached to every release |
| Release pipeline | **~4 min** (was ~22 min under QEMU) |
| Citations confirmed at source | **318 of 330 (96.4%)** across the eight showcase runs |
| Showcase verdicts reproduced from the index | **64 of 64** cells recomputed with no model call, 0 moved |
| Capacity-exhaustion detection | **9 failed calls**, all credentials open ([INCIDENT-001](docs/INCIDENT-001.md)) |
| End-to-end latency (replay) | **p50 4.9 s · p95 6.9 s**, 0 server errors |
| Backpressure under load | 45 admitted, **36 refused with 429** — never queued |
| End-to-end latency (live) | **78.9 s** upload → exported PDF, one run, 11 model calls |
| Rollout and rollback | **8.8–9.4 s** each, **0 of 921** probes failed across three drills |

**Observability:** `make observability` brings up Prometheus, Grafana and
Jaeger. The dashboard is provisioned from
[a committed JSON file](observability/grafana/dashboards/meridian.json) —
citation pass rate, coverage verdict distribution, per-stage latency, and
provider failover events ([rendered under replay traffic](docs/img/grafana-dashboard.png)) —
and every analysis is one OpenTelemetry trace, with a span per pipeline stage
and its trace id on every log line.

**Operations:** [RUNBOOK.md](docs/RUNBOOK.md) — SLOs with targets and measured
values kept separate, five failure modes with detection → diagnosis →
response → recovery, and rollback tied to image digests.
[INCIDENT-001.md](docs/INCIDENT-001.md) — a 429 storm induced on purpose
against a mocked provider, with what the signals showed and what the fix was.

---

## What it does

| Capability | What you get |
|---|---|
| **Workspace** | Create per-country workspaces, upload policy PDFs, and run the full analysis pipeline in the background |
| **Analysis** | Per-dimension evaluations across four sections — coverage verdicts, recommendations, implementation roadmaps, and relevant real-world incidents |
| **Executive Brief** | A synthesized, decision-maker-ready brief (one LLM synthesis call), cached server-side, exportable as PDF or DOCX |
| **AI Auditor** | A chat assistant that answers questions about the analysis, the framework library, or an uploaded document — with verified citations |
| **Framework Library** | Browse all indexed frameworks with indexing status, official sources, and chunk counts |

---

## How the analysis works

```
Policy PDF
  → PDF validation (type, size, password, empty, OCR detection)
  → Structure-aware chunking (headers/clauses first, then recursive split)
  → Embeddings (BAAI/bge-small-en-v1.5) → ChromaDB (persistent vector store)
  → Per-dimension retrieval (document chunks + routed frameworks)
  → Evaluation + recommendations: one LLM call per dimension, bounded-parallel
  → Normative-force scoring → coverage + implementation depth + priority (code, not LLM)
  → Mechanism check: does each matched provision establish the mechanism? (can only remove)
  → Citation verification (chunk exists · page matches · text supports claim)
  → Roadmap + case intelligence: one call for every Partial/Missing dimension
  → Decision analytics → Executive brief (cached) → PDF/DOCX export
```

### The 8 governance dimensions

Defined once in `backend/src/gap_analyzer.py` (`GOVERNANCE_DIMENSIONS`) and used
by every pipeline stage — evaluation, recommendations, implementation depth, consistency, and chat:

| Dimension | Focus |
|---|---|
| Transparency | Disclosure of AI capabilities and limitations; explainability |
| Accountability | Allocation of responsibility, liability, oversight, redress |
| Privacy | Data protection, consent, anonymisation, security |
| Safety | Risk identification, impact assessment, testing, incident monitoring |
| Human Autonomy | Human control, human-in-the-loop, right to human review |
| Inclusivity | Equitable access, non-discrimination, accessibility |
| Fairness | Bias testing and mitigation, demographic parity, inclusive design |
| Environmental Sustainability | Energy efficiency, carbon reporting, e-waste management |

### The four analysis sections (per dimension)

| Section | Content | When it runs |
|---|---|---|
| **Evaluation** (governance dimension evaluation) | Coverage verdict (`Covered` / `Partial` / `Missing`), reasoning, implementation depth stage, the evidence it rests on, document + framework evidence | Always |
| **Recommendations & Alignment** | Recommendations, deterministic priority, international standard reference, structured framework synthesis (consensus / differences / overall); for Fully Covered dimensions: best practices + international examples instead | Always |
| **Implementation Roadmap** | Phased roadmap with deterministic timeline estimates, responsible agency (code-grounded, never fabricated), documentation requirements, monitoring checklist | Only for `Partial` / `Missing` dimensions |
| **Case Intelligence** | Matched real incidents (AI Incident Database, Robodebt Royal Commission, Allegheny AFST, and other curated records) with lessons learned | Only when a genuinely relevant incident match exists |

A full analysis makes **about ten LLM calls**: one mechanism check for the whole
workspace, one evaluation + recommendations call per dimension, and one roadmap +
case-intelligence call carrying every `Partial` / `Missing` dimension (skipped
when there are none). Evaluation stays per dimension on purpose: sharing one
reply across all eight was measured to cut citations per dimension by about a
third. `BATCH_EVALUATION=1` shares it anyway, for three calls a run, when quota
matters more than citation depth; `BATCH_LLM_CALLS=0` sends every roadmap
separately too (9–17 calls). A shared reply that comes back malformed is
retried once as two halves.

### Deterministic framework selection

Which frameworks are searched is decided **in code, never by the LLM**
(`backend/src/framework_router.py`):

- **Core normative sources** (evaluation) and **practical tools**
(recommendations) are always part of the retrieval budget.
- **Dimension-tagged sources** are *guaranteed* a retrieval slot for their
  dimension (e.g. the World Bank's Digital Progress report is reserved for
  Inclusivity; the CDEI bias review for Fairness).
- **Regional frameworks** (ASEAN, African Union) are routed by the workspace's
  country — a Singapore strategy automatically searches the ASEAN + Singapore
  generative-AI sources.

---

## Anti-fabrication & determinism (the core design)

Meridian's design principle is that **the LLM never decides verdicts, priorities,
timelines, or institutions** — those are derived from evidence in code.

### Verdicts are computed from the document, then explained

The verdict for each dimension is decided **before** the model is called, from
the document's own provisions, and handed to the model as a fixed input to
explain. The model writes the reasoning; it never sets the verdict.

- **Every provision is graded on a normative-force ladder** — T0 Aspirational,
  T1 Intentional, T2 Assigned, T3 Obligatory, T4 Enforceable — from who it
  addresses, how firmly (shall / must / should), and what consequence attaches
  (penalty, fine, liability). This follows the Abbott & Snidal legalization
  framework (obligation, precision, delegation). Recitals, definitions and
  headings are excluded before anything is counted, and duplicate provisions
  from overlapping chunks are collapsed.
- **The whole supplied text is read**, not a sample: every operative sentence
  of every uploaded document is scored, so a thin count means the document
  barely addresses a dimension rather than that too little was retrieved.
- **Coverage** — `Covered` needs two binding provisions, or one paired with an
  enforceable one, *and* those duties must reach at least a third of the
  mechanisms the dimension calls for. `Partial` is a duty that stands alone, a
  commitment without a duty, or binding force spread too narrowly. `Missing`
  is a dimension the document mentions only in passing.
- **Implementation depth** — five stages, each a strictly stronger claim than
  the last: Unaddressed, Emerging, Delegated, Operationalized,
  Institutionalized. A dimension cannot be Operationalized unless at least one
  of its expected mechanisms is carried by a duty, nor Institutionalized with
  fewer than two. This gate only ever lowers a stage.
- **Two indices, never one** — the depth index (mean stage score, 0–100) says
  how hard the provisions bind; the coverage index says how much of each
  dimension's expected mechanisms they reach at all. They are reported side
  by side because the interesting cases are where they diverge: a narrow
  statute that binds hard, a broad strategy that binds nobody.
- **Where a model touches the verdict path** — once, and only downward. A
  model checks whether a provision that mentions a mechanism actually
  establishes it; it can remove a mechanism, never add one, and the gates it
  feeds only lower a verdict. If that check is unavailable, the run is marked
  provisional rather than passed off as complete.
- **Priority is tiered in code** — `Covered` → none; `Partial` → Medium (High
  when a cluster dimension is also open); `Missing` → High (Critical when a
  cluster dimension is also open).

### Every citation is verified

- Each cited chunk is checked three ways: **does the chunk exist? does the page
  match? is the quoted excerpt consistent with the chunk it came from?** The
  third is an embedding-similarity check (`BAAI/bge-small-en-v1.5`, cosine
  >= 0.65) with a keyword-overlap fallback at 0.30.
- An NLI cross-encoder (`cross-encoder/nli-deberta-v3-base`) was measured as
  the third check and not adopted — see [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).
  On the 344 stored citations whose excerpt appears verbatim in the chunk it
  cites — where fabrication is impossible by construction — the embedding check
  accepts 88.7% and the NLI check 29.1%.
- If no retrieved passage supports a claim, the model emits an explicit
  **"no citation"** sentinel — an honest decline, never a fabricated citation.
- Low-information glossary/index fragments (e.g. "Explainability15" from PDF
  extraction) are detected and never become evidence.
- When a dimension needs a citation and none was found, a deterministic
  fallback attaches the top **dimension-grounded** chunk — explicitly marked
  as added rather than quoted, so it's never shown as verified.
- Roadmap citations are **dimension-grounded**: a top-ranked but off-topic
  chunk (generic risk-assessment boilerplate) is dropped, even if the LLM cited
  it, because a verified-but-irrelevant citation is worse than honest absence.
- Recommendations that name institutions are **document-grounded**: a
  body (e.g. "MeitY", "Bureau of Indian Standards") is only surfaced when it
  appears verbatim in the uploaded document — the model can't name an agency
  from its own knowledge.
- The roadmap's responsible agency is classified in code as
  `document_named` / `document_implied` / `none_identified` — never fabricated,
  and never inherited from the recommendations unless the cross-reference
  verifies it.
- Roadmap timelines are **computed, not guessed**: phase ranges derive from
  coverage tier, existing operational mechanisms, implementation depth, agency grounding,
  and scope — with the reasoning string exposed in the UI.
- A deterministic **scope disclaimer** states plainly that the analysis
  evaluates only the document(s) provided, never the country's complete
  governance apparatus.

### Every verdict says what it rests on

Each dimension carries a plain statement of the evidence behind it — how many
provisions were read, how many bind, how many carry a consequence — in three
coarse bands (strong, moderate, thin) rather than a percentage. A precise-looking
confidence score built from counts would be exactly the kind of unearned
precision the scorer exists to avoid.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy (async) |
| Vector store | ChromaDB (persistent, embedded) + `BAAI/bge-small-en-v1.5` embeddings |
| LLM | **Gemini** (quota-aware routing, per-key RPM/RPD throttles, failover and backoff across configured credentials) |
| Verification | Verbatim containment first, then `BAAI/bge-small-en-v1.5` embedding similarity with a keyword-overlap fallback |
| Database | PostgreSQL 16 |
| Frontend | Next.js 14 (prerendered; standalone or static export), React 18, TypeScript, Tailwind, Motion, hand-built SVG charts |

### LLM provider strategy

One model, `gemini-3.5-flash-lite`, and one key is the supported
configuration. The provider router (`backend/src/provider_router.py`):

- enforces a **rolling RPM throttle** and a **daily request cap** (persisted to
  `data/gemini_rpd.json` so restarts don't reset the day's count);
- retries with **jittered backoff** so concurrent dimension calls don't
  re-collide on the same quota window;
- honours the delay the API itself asks for when quota is exhausted, and
  fails the run with a clear message rather than a half-finished brief.

It also accepts `GEMINI_API_KEY_2`…`_9` for deployments that legitimately hold
several credentials (separate projects per environment, or a key rotation
window). It is not a way to multiply free-tier quota; `.env.example` explains
why.

---

## Getting started

### Prerequisites

- Docker and Docker Compose v2, **or** [uv](https://docs.astral.sh/uv/) + Node 20+ for local dev
- A **Gemini API key** (free tier works) — set `GEMINI_API_KEY` in `.env`

Everything else, including PostgreSQL and the Python 3.13 interpreter, is
brought up by the targets below.

### Quick start

```bash
cp .env.example .env          # add your GEMINI_API_KEY
make up                       # API, Postgres, Azurite and frontend
make ready                    # blocks until /readyz reports ready
```

- Frontend: `http://localhost:3000`
- API: `http://localhost:8000` (interactive docs at `/docs`)

### Every instruction is a make target

| Target | What it does |
|---|---|
| `make setup` | Install the locked dependency set and frontend packages |
| `make up` / `make down` | Bring the stack up / stop it |
| `make ready` | Poll `/readyz` until every dependency reports healthy |
| `make test` | Run the suite with the coverage gate |
| `make test-container` | Run the suite **inside the built image**, as CI does |
| `make lint` / `make typecheck` | ruff and mypy, the same commands CI runs |
| `make check` | Everything CI runs, in CI's order |
| `make build` | Build the production image |
| `make bench` | Re-measure what `docs/MEASUREMENTS.md` reports (no Gemini calls) |
| `make deploy` / `make destroy` | Production stack up / torn down with volumes |
| `make logs` `make ps` `make shell` `make clean` | The usual |

Run `make` with no arguments for the same list.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg` | PostgreSQL connection |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model. Free tier: 500 requests a day, where every full Flash model allows 20. The eight showcase runs were scored on `gemini-3.5-flash`; verdicts are computed in code either way |
| `GEMINI_API_KEY` | — | Gemini key |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store location |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `SUBSTANTIVE_RELEVANCE_THRESHOLD` | `0.62` | How close a passage must sit to a dimension before it is cited as a requirement (model-dependent) |
| `BATCH_LLM_CALLS` | `1` | One roadmap call for all gapped dimensions instead of one each |
| `BATCH_EVALUATION` | `0` | One evaluation call for all dimensions (3 calls a run, fewer citations) |
| `ANALYSIS_MAX_CONCURRENCY` | `3` | Parallel dimension workers when batching is off |
| `GEMINI_RPM_LIMIT` / `GEMINI_RPD_LIMIT` | `3` / off | Requests per minute per credential; optional self-imposed daily cap |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Frontend → API base URL (baked at build time) |
| `ADMIN_TOKEN` | unset | Bearer token for `POST /frameworks/sync`; unset, the endpoint is refused |
| `LOCKED_WORKSPACE_IDS` | unset | Read-only example workspaces on a public demo |
| `FRONTEND_DIST` | unset | A static export of the frontend for the API to serve on the same origin |

---

## API

All endpoints under `/api/v1`. Interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health + vector store status (chunk/framework counts) |
| `GET` | `/frameworks` | Framework library with indexing status |
| `POST` | `/frameworks/sync` | Re-index frameworks whose PDF changed (operator only: `ADMIN_TOKEN`) |
| `POST` | `/workspace` | Create a workspace (country, policy title) |
| `GET` | `/workspace` · `/workspace/{id}` | List / fetch workspaces |
| `POST` | `/upload/{workspace_id}` | Upload a policy PDF (queued for the next run) |
| `POST` | `/analyze/{workspace_id}/run` | Run the analysis over every queued document, in the background |
| `GET` | `/analyze/{workspace_id}` | Every run for the workspace, which dimensions each is missing, and the newest complete run |
| `POST` | `/auditor/upload` | AI Auditor: ingest a PDF for chat only (no analysis) |
| `POST` | `/brief/{workspace_id}/generate` | Generate the executive brief (one synthesis call) |
| `GET` | `/brief/{workspace_id}` | Fetch the cached brief |
| `GET` | `/brief/{workspace_id}/export?format=pdf\|docx` | Export the cached brief (no LLM call) |
| `POST` | `/chat` | Chat (4 modes: `advisor`, `framework_qa`, `document_overview`, `auditor`) |
| `GET` | `/chat/sessions` · `/chat/sessions/{id}` | List / fetch chat sessions |

### Typical flow

```bash
# 1. Create a workspace
curl -X POST http://localhost:8000/api/v1/workspace \
  -H "Content-Type: application/json" \
  -d '{"country":"India","policy_title":"National AI Strategy"}'

# 2. Upload the policy PDF (repeat for each document in the workspace)
curl -X POST http://localhost:8000/api/v1/upload/{workspace_id} \
  -F "file=@national-ai-strategy.pdf"

# 3. Run the analysis over everything uploaded, then poll for the result
curl -X POST http://localhost:8000/api/v1/analyze/{workspace_id}/run
curl http://localhost:8000/api/v1/analyze/{workspace_id}

# 4. Generate + download the executive brief
curl -X POST http://localhost:8000/api/v1/brief/{workspace_id}/generate
curl -o brief.pdf "http://localhost:8000/api/v1/brief/{workspace_id}/export?format=pdf"
```

---

## Frontend

Every route prerenders, and every page is a client component reading the API,
so the same pages ship two ways: the standalone Next server behind Caddy (the
compose stack), or a plain static export (`NEXT_OUTPUT=export`) that the API
serves itself through `FRONTEND_DIST` — the single-container shape the hosted
demo uses.

| Route | Page |
|---|---|
| `/` | Landing — scroll-scrubbed hero film, a sideways track through the standards, the reading and the Auditor, then the method and the close |
| `/workspace` | Create workspaces, upload policy PDFs, watch analysis status |
| `/analysis` | Per-dimension cards: evaluation, recommendations, roadmap, and case intelligence, with collapsible evidence toggles |
| `/brief` | Executive brief preview, coverage dashboard, PDF/DOCX export |
| `/auditor` | AI Auditor chat — ask about the analysis, the framework library, or an uploaded document |
| `/frameworks` | Framework library — every indexed source with status and links |

---

## Testing

```bash
make test            # the suite with the coverage gate
make test-container  # the same suite INSIDE the built image, as CI does
make check           # lint, types and tests, in CI's order
```

**1,395 passed, 26 skipped. Coverage 82%** on `src`. The CI gate is 80% —
set below measured, so it catches regression without being aspirational.
The suite writes every piece of state (index, uploads, quota ledger) to a
throwaway directory, so it is safe to run beside a live API.

The skips are deliberate and need external state (Azurite, an indexed
framework corpus, running services, or a Gemini key for the live gate):

```bash
RUN_INTEGRATION_TESTS=1 make test   # requires running services
RUN_EVALUATION_TESTS=1  make test   # requires an indexed framework corpus
MERIDIAN_LIVE_GATE=1    make test   # the Tier-2 gate: ten live Gemini requests
```

What is covered: an evidence gate that replays a full analysis against both
a scripted provider and real recorded Gemini answers, asserting that every
citation resolves and verdicts are byte-identical across runs; the scorer's
reading of the EU AI Act and the UK AI white paper, pinned against a
committed snapshot; PDF validation failure modes, structure-aware chunking,
citation verification (including deliberately broken cases), the
normative-force scorer and its gates, an AST guard
against a second verdict computation reappearing, guardrails, framework
routing and role filtering, brief generation, stability, orphan recovery, and
the liveness/readiness split.

Least covered, stated plainly: `workspace.py` at 43% and `tasks.py` (the
pipeline orchestrator) at 49% — both mostly database and background-task
paths — then `chat.py` at 72%. `provider_router.py` is at 91%.

---

## Deployment

See **[LAUNCH.md](LAUNCH.md)** for the full runbook. In short:

- **Recommended:** a single VPS (4 GB RAM / ~30 GB disk) running
  `docker-compose.prod.yml` with Caddy TLS — the only option that survives
  long in-process analyses without sleeping.
- **Demo:** a single-container build for a Hugging Face Docker Space lives in
  [deploy/huggingface](deploy/huggingface) — Postgres, the API and the static
  frontend in one image, with the eight country analyses as read-only examples.
- **Critical:** `backend/data/chroma` (the indexed corpus — much of it ingested
  from local files with **no public URL**) and `backend/data/uploads` **cannot
  be recreated** and must be shipped with the app.
- **Security:** there is **no user auth layer** — anyone with the URL can spend
  the Gemini quota. Keep a production site private (the Caddyfile has a basic
  auth block ready to enable) until auth is built; the public demo runs on
  free-tier keys whose own limits are the ceiling.

---

## Known limitations

- **No authentication** — no user/auth layer; intended for portfolio/team
  demonstration, not multi-tenant production.
- **Scanned PDFs** — no OCR. Scanned image PDFs are detected and flagged, not
  processed.
- **Non-English documents** — tuned for English; other languages degrade
  retrieval quality.
- **Background tasks** — FastAPI `BackgroundTasks` (adequate at portfolio scale;
  lost on restart; Celery + Redis is the planned upgrade).
- **LLM quota** — a run makes about ten requests, a brief one more, a chat
  reply one each. Free-tier quota is counted per Google project;
  `BATCH_EVALUATION=1` cuts a run to three requests at a cost in citation
  depth.

---

## Project structure

```
Meridian/
├── config/
│   └── frameworks.yaml           # All indexed frameworks: roles, dimension tags, regions, URLs
├── backend/
│   ├── data/
│   │   ├── raw_policies/         # Ingested framework PDFs (gitignored)
│   │   ├── chroma/               # ChromaDB persistence (gitignored)
│   │   └── uploads/              # Uploaded policy PDFs (gitignored)
│   ├── src/
│   │   ├── tasks.py                  # Background pipeline: ingest every document, analyse, verify, save
│   │   ├── validation.py             # PDF validation (type, size, password, empty, OCR)
│   │   ├── ingestion.py              # PDF parsing, split-word repair, chunking, division titles
│   │   ├── text_repair.py            # Rejoins words a PDF extractor split ("shal l" → "shall")
│   │   ├── vectorstore.py            # ChromaDB + embeddings
│   │   ├── hybrid_search.py          # BM25 fused with dense retrieval by reciprocal rank fusion
│   │   ├── retrieval.py              # Per-dimension retrieval, budget reserves, scoring pools
│   │   ├── framework_router.py       # Deterministic framework selection (roles, tags, regions)
│   │   ├── gap_analyzer.py           # Per-dimension orchestration; the single place a verdict is set
│   │   ├── grading.py                # Provision classification, de-duplication, depth and mechanism gates
│   │   ├── evidence_strength.py      # Normative-force ladder, evidence profile, coverage and depth
│   │   ├── mechanism_matching.py     # Which expected mechanisms a dimension's provisions evidence
│   │   ├── mechanism_adjudication.py # Model check that a matched provision establishes the mechanism
│   │   ├── framework_salience.py     # How many reference instruments expect each mechanism
│   │   ├── deterministic.py          # Dimension vocabularies, low-information filter, fallback ladder
│   │   ├── analysis_prompts.py       # Prompts for the evaluation and roadmap calls
│   │   ├── consistency.py            # Cross-dimension consistency and narrative-drift detection
│   │   ├── evidence_agreement.py     # Cross-source evidence agreement scoring
│   │   ├── verify.py                 # Citation verification (passage exists · page · supports claim)
│   │   ├── models.py                 # Pydantic models for the analysis output
│   │   ├── provider_router.py        # LLM routing: key rotation, throttles, backoff
│   │   ├── provider_errors.py        # What a provider failure means for the retry loop
│   │   ├── key_health.py             # Per-credential circuit breakers and daily accounting
│   │   ├── llm_provider.py           # Provider client (Gemini)
│   │   ├── concurrency.py            # Admission control for concurrent analyses
│   │   ├── brief_synthesis.py        # Executive brief (one synthesis call, cached)
│   │   ├── brief_emphasis.py         # Marks the key terms in each brief paragraph
│   │   ├── brief_export.py           # DOCX / PDF rendering from the cached brief
│   │   ├── chat.py                   # Chat assistant (AI Auditor / Rapporteur)
│   │   ├── governance_advisor.py     # Intent routing and advisor responses
│   │   ├── meridian_facts.py         # The instrument's own method, derived from live constants
│   │   ├── analysis_brief.py         # The open run compacted as chat context
│   │   ├── document_overview.py      # Section-stratified overview of an uploaded document
│   │   ├── guardrails.py             # Off-topic rejection
│   │   ├── framework_library.py      # Framework Library metadata and indexing status
│   │   ├── framework_sync.py         # Config-driven framework sync
│   │   ├── workspace.py              # Workspace service
│   │   ├── db_models.py              # PostgreSQL ORM models
│   │   ├── storage.py                # Filesystem / Azure Blob storage for uploads
│   │   ├── provenance.py             # What produced a result: model, calls, code revision
│   │   ├── replay.py                 # Recorded-provider replay for load tests
│   │   ├── metrics.py                # Prometheus metrics
│   │   ├── logging_config.py         # Structured JSON logging
│   │   └── utils.py                  # Shared helpers
│   ├── scripts/                  # Index rebuild, framework resync, measurement
│   ├── tests/                    # unit / integration / evaluation / live, golden set, recorded replay
│   ├── main.py                   # FastAPI app
│   ├── Dockerfile
│   ├── pyproject.toml           # dependencies, ruff/mypy/pytest config
│   └── uv.lock                  # fully resolved, committed
├── frontend/
│   ├── app/                      # workspace / analysis / brief / auditor / frameworks / landing
│   ├── components/               # Page components; analysis/ holds the four module panels
│   └── lib/                      # Typed API client, palette, framework links, motion helpers
├── deploy/                       # rollout.sh (zero-downtime deploy and rollback), Hugging Face demo image
├── docs/                         # Runbook, measurements, incident write-up
├── loadtest/                     # k6 load test (replay mode, no Gemini calls)
├── observability/                # Prometheus + Grafana, dashboard as code
├── docker-compose.yml            # Dev: api + web + postgres + azurite
├── docker-compose.prod.yml       # Prod: persistent volumes, healthchecks, Caddy TLS
├── Caddyfile                     # Caddy reverse proxy config
├── LAUNCH.md                     # Deployment runbook
└── .env.example                  # Environment template
```

---

## Design principles

- **Honest output** — every claim in the UI is backed by real pipeline state.
  No hardcoded demo data, no templated answers dressed up as analysis.
- **Verified citations** — every cited chunk is programmatically checked; the
  "no citation" state is explicit, never masked.
- **No training-data answers** — the LLM only answers from retrieved context,
  and never names institutions, timelines, priorities, or verdicts the evidence
  doesn't support.
- **Deterministic where it matters** — coverage, implementation depth, priority, risk,
  timelines, and responsible agencies are decided in code, reproducible across
  runs, and auditable.
- **Testable building blocks** — every file in `src/` is independently unit-testable.
- **Clean separation** — the backend has zero knowledge of the frontend; all
  communication is HTTP/JSON.
