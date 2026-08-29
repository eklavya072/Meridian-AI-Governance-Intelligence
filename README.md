# Meridian — AI Governance Intelligence Workbench

**Meridian** analyzes national AI policy documents against international governance
frameworks and produces an evidence-verified, decision-ready assessment. Upload a
policy PDF — a national AI strategy, a sectoral framework, a draft bill — and
Meridian evaluates it across **8 governance dimensions**, grounded in a curated
corpus of **international standards** (OECD AI Principles, UNESCO Recommendation,
EU AI Act, NIST AI RMF, UN Global Digital Compact, and more), then generates an
executive brief you can export as PDF or DOCX.

Every verdict is backed by **verifiable citations** — every claim is traced to a
real chunk of a real document, checked programmatically (chunk exists, page
matches, and the passage supports the claim via an NLI cross-encoder). Nothing is
invented: where the evidence doesn't support a claim, Meridian says so.

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
  → Combined evaluation + recommendations LLM call (per dimension, bounded-parallel)
  → Deterministic coverage ladder + maturity + priority (code, not LLM)
  → Citation verification (chunk exists · page matches · text supports claim)
  → Conditional roadmap + case-intelligence calls (Partial/Missing dimensions)
  → Decision analytics → Executive brief (cached) → PDF/DOCX export
```

### The 8 governance dimensions

Defined once in `backend/src/gap_analyzer.py` (`GOVERNANCE_DIMENSIONS`) and used
by every pipeline stage — evaluation, recommendations, maturity, consistency, and chat:

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
| **Evaluation** (governance dimension evaluation) | Coverage verdict (`Covered` / `Partial` / `Missing`), reasoning, governance maturity (Institutionalization Scale), document + framework evidence | Always |
| **Recommendations & Alignment** | Recommendations, deterministic priority, international standard reference, structured framework synthesis (consensus / differences / overall); for Fully Covered dimensions: best practices + international examples instead | Always |
| **Implementation Roadmap** | Phased roadmap with deterministic timeline estimates, responsible agency (code-grounded, never fabricated), documentation requirements, monitoring checklist | Only for `Partial` / `Missing` dimensions |
| **Case Intelligence** | Matched real incidents (AI Incident Database, Robodebt Royal Commission, Allegheny AFST, and other curated records) with lessons learned | Only when a genuinely relevant incident match exists |

A full analysis makes **8 evaluation calls** (one per dimension, each combining
evaluation + recommendations, run concurrently with bounded parallelism) **plus
up to 8 conditional roadmap + case-intelligence calls** for `Partial` / `Missing`
dimensions — so between 8 and 16 LLM calls total. Fully Covered dimensions cost
exactly one call.

### Deterministic framework selection

Which frameworks are searched is decided **in code, never by the LLM**
(`backend/src/framework_router.py`):- **Core normative sources** (evaluation) and **practical tools**
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

### Coverage is a deterministic ladder

After the model returns its raw verdict for a dimension, a deterministic ladder
(`backend/src/deterministic.py`) enforces rules in code, keyed off the document's
own retrieved chunks and the model's mechanism report — never a hard-coded
country/verdict expectation.

- **Six maturity levels (0–5)** — from "No Governance Intent" to "Continuous
  Monitoring & Enforcement", mapped to `Missing` / `Partial` / `Covered`.
- **Rule R1 (the "explicit commitment" floor)** — a raw `Missing` verdict is
  raised to `Partial` only when the document shows an *actual attempted
  mechanism or explicit commitment* (a named body, a `will establish` /
  `roadmap` / `programme` commitment). A bare risk acknowledgment does **not**
  qualify.
- **Rule R2 (the implementation-commitment raise)** — `Partial` is raised to
  `Covered` only on a concrete implementation commitment (operational
  mechanism, named programme, or corroborated commitment phrases).
- **Substantive specificity gate (anti-false-positive)** — before the broad
  evidence pool can fire R1/R2, the chunk's mechanism-bearing sentences must be
  semantically close to the dimension's profile above
  `SUBSTANTIVE_RELEVANCE_THRESHOLD` (default `0.62`). This is the
  "procedural authority ≠ substantive governance mechanism" rule: a provision
  that merely assigns a minister/body a power to approve, support, or
  administer something (e.g. "the Minister may approve/support AI data
  centres")  passes the loose relevance gate but is not a governance mechanism
  for the dimension, so it never raises a verdict. Genuine mechanisms scored
  0.64–0.80 against their dimension's aspects during calibration; procedural
  provisions scored 0.48–0.59.
- **Sentence-level evidence discipline (R1/R2 chunk paths)** — the gates are
  evaluated on the *sentence* that carries the commitment/obligation phrase
  (and, for R2, the named responsible body in the same sentence), never on
  the whole chunk. A long chunk can contain a genuine dimension mechanism in
  one sentence and an unrelated strong obligation phrase / named body in
  another (e.g. a mixed Article 32/33 safety chunk promoting Fairness on a
  safety provision); co-located evidence elsewhere in the chunk never
  satisfies the requirement.
- **Ladder-raise review safeguard** — when a deterministic raise produces a
  final verdict that contradicts the model's own coverage reasoning (gap
  assertions like "does not establish", "no provisions", "lacks",
  "provides no", "establishes no"...), the card is flagged for review
  instead of shipping the mismatch silently.
- **Priority is tiered in code** — `Covered` → none; `Partial` → Medium (High
  when a cluster dimension is also open); `Missing` → High (Critical when a
  cluster dimension is also open).
- **Risk is cluster-aware** — core dimensions escalate; gaps in related
  dimensions compound risk.
- **Overall maturity uses the weakest-dimension rule on the Institutionalization
  Scale** (`Unaddressed` → `Emerging` → `Formalized` → `Operationalized` →
  `Institutionalized`) — the policy is as mature as its least mature dimension,
  plus a continuous 0–100 composite index.

Toggle the R1 floor with `LADDER_FLOOR_ENABLED=0` for a strict "no floor"
baseline (read at startup).

### Every citation is verified

- Each cited chunk is checked: **does the chunk exist? does the page match?
  does the passage support the claim?** — the last via an NLI cross-encoder
  (`cross-encoder/nli-deberta-v3-base`).
- If no retrieved passage supports a claim, the model emits an explicit
  **"no citation"** sentinel — an honest decline, never a fabricated citation.
- Low-information glossary/index fragments (e.g. "Explainability15" from PDF
  extraction) are detected and never become evidence.
- When a dimension needs a citation and none was found, a deterministic
  fallback attaches the top **dimension-grounded** chunk — explicitly marked
  *auto-attached, not LLM-grounded*, so it's never shown as verified.
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
  coverage tier, existing operational mechanisms, maturity, agency grounding,
  and scope — with the reasoning string exposed in the UI.
- A deterministic **scope disclaimer** states plainly that the analysis
  evaluates only the document(s) provided, never the country's complete
  governance apparatus.

### Confidence is calibrated, not guessed

Confidence scores are the **geometric mean of seven evidence factors** — quality
(mean similarity), diversity (unique sources), agreement, retrieval stability,
citation strength, cross-source agreement, and coverage completeness — each
derived from real pipeline state, never an LLM self-assessment.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async) |
| Vector store | ChromaDB (persistent, embedded) + `BAAI/bge-small-en-v1.5` embeddings |
| LLM | **Gemini** (primary, multi-key rotation + RPM/RPD throttles), **Groq** fallback |
| Verification | `cross-encoder/nli-deberta-v3-base` NLI cross-encoder |
| Database | PostgreSQL 16 |
| Frontend | Next.js 14 (fully static output), React 18, TypeScript, Tailwind, Motion (Framer Motion), Recharts |

### LLM provider strategy

`LLM_PROVIDER=gemini` is the default. The provider router (`backend/src/provider_router.py`):

- rotates **multiple Gemini keys** (`GEMINI_API_KEY`, `GEMINI_API_KEY_2/3/4`)
  to spread free-tier quota;
- enforces a **rolling RPM throttle** and a **daily request cap** (persisted to
  `data/gemini_rpd.json` so restarts don't reset the day's count);
- retries with **jittered backoff** so concurrent dimension calls don't
  re-collide on the same quota window;
- falls back to **Groq** when all Gemini keys are exhausted.

---

## Getting started

### Prerequisites

- Docker and Docker Compose v2 **or** Python 3.12 + Node 18+ for local dev
- PostgreSQL 16 (Docker image provided in compose)
- A **Gemini API key** (free tier works) — set `GEMINI_API_KEY` in `.env`

### Quick start (Docker)

```bash
cd aura-sdg
cp .env.example .env          # add your GEMINI_API_KEY
docker compose up --build
```

- Backend: `http://localhost:8000` (interactive docs at `/docs`)
- Frontend: `http://localhost:3000`
- PostgreSQL: `localhost:5432`

### Without Docker

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env       # add GEMINI_API_KEY, DATABASE_URL
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev                   # NEXT_PUBLIC_API_URL defaults to localhost:8000/api/v1
```

Requires PostgreSQL running locally:

```bash
docker run -d --name meridian-pg -e POSTGRES_USER=aura -e POSTGRES_PASSWORD=aura \
  -e POSTGRES_DB=aura_sdg -p 5432:5432 postgres:16-alpine
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://aura:aura@localhost:5432/aura_sdg` | PostgreSQL connection |
| `LLM_PROVIDER` | `gemini` | `gemini` \| `groq` |
| `GEMINI_MODEL` | `gemini-3.6-flash` | Gemini model |
| `GEMINI_API_KEY` | — | Primary Gemini key (add `_2`/`_3`/`_4` for rotation) |
| `GROQ_API_KEY` | — | Groq fallback provider |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Vector store location |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins |
| `LADDER_FLOOR_ENABLED` | `1` | Enable the R1 commitment floor (see methodology) |
| `SUBSTANTIVE_RELEVANCE_THRESHOLD` | `0.62` | Substantive-specificity bar for the ladder's anti-false-positive gate (model-dependent) |
| `ANALYSIS_MAX_CONCURRENCY` | `3` | Parallel dimension-analysis workers |
| `GEMINI_RPM_LIMIT` / `GEMINI_RPD_LIMIT` | `10` / `1000` | Free-tier throttle ceilings |
| `LOG_LEVEL` / `DEV_MODE` | `INFO` / `false` | Logging + dev behavior |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Frontend → API base URL (baked at build time) |

---

## API

All endpoints under `/api/v1`. Interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health + vector store status (chunk/framework counts) |
| `GET` | `/frameworks` | Framework library with indexing status |
| `POST` | `/frameworks/sync` | Re-sync frameworks from `config/frameworks.yaml` |
| `POST` | `/workspace` | Create a workspace (country, policy title) |
| `GET` | `/workspace` · `/workspace/{id}` | List / fetch workspaces |
| `POST` | `/upload/{workspace_id}` | Upload policy PDF → starts background analysis |
| `GET` | `/analyze/{workspace_id}` | Full analysis results (8 dimensions × 4 sections) |
| `POST` | `/auditor/upload` | AI Auditor: ingest a PDF for chat only (no analysis) |
| `POST` | `/brief/{workspace_id}/generate` | Generate the executive brief (one synthesis call) |
| `GET` | `/brief/{workspace_id}` | Fetch the cached brief |
| `GET` | `/brief/{workspace_id}/export?format=pdf\|docx` | Export the cached brief (no LLM call) |
| `POST` | `/chat` | Chat (4 modes: `advisor`, `framework_qa`, `document_overview`, `auditor`) |
| `GET`/`DELETE` | `/chat/sessions[...]` | List / fetch / delete chat sessions |

### Typical flow

```bash
# 1. Create a workspace
curl -X POST http://localhost:8000/api/v1/workspace \
  -H "Content-Type: application/json" \
  -d '{"country":"India","policy_title":"National AI Strategy"}'

# 2. Upload the policy PDF (starts the background analysis pipeline)
curl -X POST http://localhost:8000/api/v1/upload/{workspace_id} \
  -F "file=@national-ai-strategy.pdf"

# 3. Poll for the completed analysis
curl http://localhost:8000/api/v1/analyze/{workspace_id}

# 4. Generate + download the executive brief
curl -X POST http://localhost:8000/api/v1/brief/{workspace_id}/generate
curl -o brief.pdf "http://localhost:8000/api/v1/brief/{workspace_id}/export?format=pdf"
```

---

## Frontend

The frontend is **fully static** — every route prerenders, so it can be hosted
anywhere (Vercel, Netlify, or behind the same Caddy instance as the API).

| Route | Page |
|---|---|
| `/` | Landing — three-section glide: hero (typed tagline), the pipeline (Ingestion → Retrieval → Analysis → Brief → AI Auditor), and the 8-dimensions statement |
| `/workspace` | Create workspaces, upload policy PDFs, watch analysis status |
| `/analysis` | Per-dimension cards: evaluation, recommendations, roadmap, and case intelligence, with collapsible evidence toggles |
| `/brief` | Executive brief preview, coverage dashboard, PDF/DOCX export |
| `/auditor` | AI Auditor chat — ask about the analysis, the framework library, or an uploaded document |
| `/frameworks` | Framework library — every indexed source with status and links |

---

## Testing

```bash
# Unit tests (no external dependencies)
cd backend && python -m pytest tests/unit/ -v

# Integration tests (requires running services + LLM)
RUN_INTEGRATION_TESTS=1 python -m pytest tests/integration/ -v

# Evaluation tests (requires indexed frameworks)
RUN_EVALUATION_TESTS=1 python -m pytest tests/evaluation/ -v
```

Coverage: PDF validation failure modes, structure-aware chunking, citation
verification (including deliberately broken cases), the deterministic coverage
ladder, guardrails, framework routing and role filtering, brief generation,
stability, and the full pipeline.

---

## Deployment

See **[LAUNCH.md](LAUNCH.md)** for the full runbook. In short:

- **Recommended:** a single VPS (4 GB RAM / ~30 GB disk) running
  `docker-compose.prod.yml` with Caddy TLS — the only option that survives
  long in-process analyses without sleeping.
- **Free frontend:** the static frontend can go on Vercel/Netlify for free;
  the API still needs an always-on host.
- **Critical:** `backend/data/chroma` (the indexed corpus — much of it ingested
  from local files with **no public URL**) and `backend/data/uploads` **cannot
  be recreated** and must be shipped with the app.
- **Security:** there is **no auth layer** — anyone with the URL can burn your
  Gemini quota. Keep the site private (Caddy basic auth) until auth is built.

---

## Known limitations

- **No authentication** — no user/auth layer; intended for portfolio/team
  demonstration, not multi-tenant production.
- **Dense retrieval only** — no hybrid (BM25 + embedding) search.
- **Scanned PDFs** — no OCR. Scanned image PDFs are detected and flagged, not
  processed.
- **Non-English documents** — tuned for English; other languages degrade
  retrieval quality.
- **Background tasks** — FastAPI `BackgroundTasks` (adequate at portfolio scale;
  lost on restart; Celery + Redis is the planned upgrade).
- **LLM quota** — analyses are designed to fit free-tier limits (8–16 calls with
  throttling and key rotation), but a full run still consumes meaningful daily
  quota.

---

## Project structure

```
aura-sdg/
├── config/
│   └── frameworks.yaml           # All indexed frameworks: roles, dimension tags, regions, URLs
├── backend/
│   ├── data/
│   │   ├── raw_policies/         # Ingested framework PDFs (gitignored)
│   │   ├── chroma/               # ChromaDB persistence (gitignored)
│   │   └── uploads/              # Uploaded policy PDFs (gitignored)
│   ├── src/
│   │   ├── gap_analyzer.py       # 8-dimension × 4-section analysis orchestration
│   │   ├── retrieval.py          # Per-dimension retrieval + dimension-tagged budget reserves
│   │   ├── framework_router.py   # Deterministic framework selection (roles, tags, regions)
│   │   ├── deterministic.py      # Coverage ladder (R1/R2), maturity, low-information filter
│   │   ├── provider_router.py    # LLM routing: Gemini rotation, throttles, Groq fallback
│   │   ├── llm_provider.py       # Provider clients (Gemini / Groq)
│   │   ├── verify.py             # Citation verification (chunk / page / NLI text support)
│   │   ├── nli_verifier.py       # NLI cross-encoder wrapper
│   │   ├── ingestion.py          # PDF parsing + structure-aware chunking
│   │   ├── validation.py         # PDF validation (type, size, password, empty, OCR)
│   │   ├── vectorstore.py        # ChromaDB + embeddings
│   │   ├── brief_synthesis.py    # Executive brief (one synthesis call, cached)
│   │   ├── brief_export.py       # DOCX / PDF rendering from the cached brief
│   │   ├── chat.py               # Chat assistant (4 modes)
│   │   ├── consistency.py        # Cross-dimension consistency + synthesis-drift detection
│   │   ├── evidence_agreement.py # Cross-source evidence agreement scoring
│   │   ├── framework_library.py  # Framework Library metadata/indexing status
│   │   ├── framework_sync.py     # Config-driven framework sync
│   │   ├── guardrails.py         # Off-topic rejection, insufficient-evidence handling
│   │   ├── tasks.py              # Background analysis pipeline
│   │   ├── workspace.py          # Workspace service
│   │   ├── db_models.py          # PostgreSQL ORM models
│   │   └── logging_config.py     # Structured JSON logging
│   ├── tests/                    # unit / integration / evaluation
│   ├── main.py                   # FastAPI app
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/                      # workspace / analysis / brief / auditor / frameworks / landing
│   ├── components/               # ModuleStack, CitationAccordion, Gauge, RadarChart, PieChart, ...
│   └── lib/                      # Typed API client, framework links, motion helpers
├── docker-compose.yml            # Dev: api + web + postgres
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
- **Deterministic where it matters** — coverage, maturity, priority, risk,
  timelines, and responsible agencies are decided in code, reproducible across
  runs, and auditable.
- **Testable building blocks** — every file in `src/` is independently unit-testable.
- **Clean separation** — the backend has zero knowledge of the frontend; all
  communication is HTTP/JSON.
