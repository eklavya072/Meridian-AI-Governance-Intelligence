# Meridian — AI Policy Intelligence Workbench

**Meridian** helps UNDP country office teams review draft national AI strategies against international governance frameworks (OECD AI Principles, UNESCO Recommendation on the Ethics of AI, UNDP Digital Strategy, UN Digital Cooperation frameworks), flagging governance gaps with verified citations, risk levels, and recommendations, then exporting the findings as a decision-maker-ready brief.

Built for the **UNDP Digital, AI and Innovation (DAI) Hub** internship application.

---

## Architecture

```
Raw Policy PDFs
  → Document Parser (pypdf)
  → Structure-Aware Splitter (headers/clauses first)
  → Recursive Character Splitter (1000 token / 15% overlap subsplit)
  → Embedding Model (BAAI/bge-small-en-v1.5 via sentence-transformers)
  → ChromaDB (persistent, metadata = {doc, section, framework})
  → Retriever (top-k cosine similarity per governance dimension, multi-framework)
  → LLM Agent + Pydantic Schema (Qwen 3 8B via Ollama, structured gap-analysis output)
  → Citation Verification (chunk_id exists, page matches, text supports claim)
  → Guardrail Check (greeting/off-topic → polite rejection; low-similarity → insufficient evidence)
  → FastAPI endpoints (/api/v1/workspace, /api/v1/upload, /api/v1/analyze, /api/v1/brief)
  → Next.js frontend (renders Explainability Chain, Country Office Workspace, Framework Library, text brief export)
```

### Services

| Service | Role | Technology |
|---------|------|-----------|
| `api` | FastAPI backend with REST endpoints | Python 3.12, FastAPI, LangChain |
| `web` | Next.js frontend | React 18, TypeScript, Tailwind |
| `postgres` | Relational store (workspace history, analysis records) | PostgreSQL 16 |

**Data stores:**
- **ChromaDB** — persistent vector store (embeddings + chunks for retrieval). No server needed.
- **PostgreSQL** — system of record: workspaces, analyses, upload logs, framework sync records, generated reports.

**Retrieval method:** Dense retrieval only (embedding-based cosine similarity via `bge-small-en-v1.5`). Hybrid dense+sparse (BM25) is a valid future enhancement but not implemented in v1.

---

## Setup

### Prerequisites

- Docker and Docker Compose v2
- [Ollama](https://ollama.com) running locally with the Qwen 3 8B model:
  ```bash
  ollama pull qwen3:8b
  ```

### Quick Start

```bash
# 1. Clone and enter the project
cd aura-sdg

# 2. Copy environment file
cp .env.example .env

# 3. Start all services
docker compose up --build
```

This starts:
- FastAPI backend at `http://localhost:8000` (API docs at `/docs`)
- Next.js frontend at `http://localhost:3000`
- PostgreSQL on port 5432

### Without Docker (for development)

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

Requires PostgreSQL running locally or via Docker:
```bash
docker run -d --name aura-pg -e POSTGRES_USER=aura -e POSTGRES_PASSWORD=aura -e POSTGRES_DB=aura_sdg -p 5432:5432 postgres:16-alpine
```

---

## API Endpoints

All endpoints are under `/api/v1/`. Full interactive docs at `/docs` when the backend is running.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Health check with vector store status |
| `GET` | `/frameworks` | List all frameworks with indexing status |
| `POST` | `/frameworks/sync` | Trigger framework re-sync (download + index updates) |
| `POST` | `/workspace` | Create a new workspace (country, policy title, frameworks) |
| `GET` | `/workspace` | List all workspaces |
| `GET` | `/workspace/{id}` | Get workspace details and status |
| `POST` | `/upload/{workspace_id}` | Upload policy PDF + start background analysis pipeline |
| `GET` | `/analyze/{workspace_id}` | Get analysis results for a workspace |
| `POST` | `/brief` | Generate executive brief (text) from completed analysis |

---

## Example: Analyze a Policy

**Request:**
```bash
# Create workspace
curl -X POST http://localhost:8000/api/v1/workspace \
  -H "Content-Type: application/json" \
  -d '{"country":"India","policy_title":"National Strategy for AI","frameworks":["OECD AI Principles","UNESCO Recommendation on the Ethics of AI"]}'

# Upload PDF (triggers async analysis)
curl -X POST http://localhost:8000/api/v1/upload/{workspace_id} \
  -F "file=@National-Strategy-for-Artificial-Intelligence.pdf"

# Get analysis results
curl http://localhost:8000/api/v1/analyze/{workspace_id}
```

**Example response (truncated):**
```json
{
  "status": "complete",
  "analyses": [{
    "analysis_id": "abc123...",
    "document_name": "National-Strategy-for-Artificial-Intelligence.pdf",
    "frameworks_used": ["OECD AI Principles", "UNESCO Recommendation on the Ethics of AI"],
    "governance_gaps": [{
      "dimension": "Transparency",
      "gap_found": true,
      "reason_flagged": "The document lacks specific provisions for algorithmic transparency...",
      "recommendation": "Include requirements for explainability of AI systems...",
      "risk_level": "High",
      "risk_reason": "Without transparency, stakeholders cannot verify AI system behavior...",
      "confidence_score": 0.82,
      "evidence": [{
        "chunk_id": "abc...",
        "text": "The OECD AI Principles state that AI systems should be transparent...",
        "page_number": 5,
        "source_framework": "OECD AI Principles",
        "similarity_score": 0.87,
        "verification": {"chunk_exists": true, "page_exists": true, "text_supports_claim": true, "passed": true}
      }]
    }]
  }]
}
```

---

## Case Study: India NITI Aayog National Strategy for AI

The project includes a demonstration analysis of India's **National Strategy for Artificial Intelligence (#AIForAll)** published by NITI Aayog (2018), against OECD AI Principles and UNESCO Recommendation on the Ethics of AI.

### Setup

```bash
# Download the document
mkdir -p backend/data/raw_policies
curl -o backend/data/raw_policies/NITI_Aayog_National_Strategy_for_AI.pdf \
  "https://www.niti.gov.in/sites/default/files/2023-03/National-Strategy-for-Artificial-Intelligence.pdf"

# Sync frameworks, ingest the document, and run analysis via the API
```

### Governance Dimensions (authoritative list)

The analysis pipeline evaluates exactly these 8 dimensions, defined once in
`backend/src/gap_analyzer.py` (`GOVERNANCE_DIMENSIONS`) and used by every
module (evaluation, recommendations, maturity, consistency, chat):

| Dimension | Focus |
|-----------|-------|
| Transparency | Disclosure of AI capabilities, limitations, decision-making; explainability |
| Accountability | Allocation of responsibility, liability, oversight, redress |
| Privacy | Data protection, consent, anonymisation, security |
| Safety | Risk identification, impact assessment, testing, incident monitoring |
| Human Autonomy | Human control, human-in-the-loop, right to human review |
| Inclusivity | Equitable access, non-discrimination, accessibility |
| Fairness | Bias testing and mitigation, demographic parity, inclusive design |
| Environmental Sustainability | Energy efficiency, carbon reporting, e-waste management |

---

## Methodology — Coverage & Maturity Determination

Coverage (`Covered` / `Partial` / `Missing`) is **not** left to free LLM
judgment. After the model returns its raw verdict for a dimension, a
deterministic ladder (`backend/src/deterministic.py`,
`validate_coverage_deterministic`) enforces the rules below in code. The
ladder is document-agnostic and reproducible — it keys off the document's
own retrieved chunks and the model's mechanism report, never off a
hard-coded country/verdict expectation.

### The six governance-maturity levels

Each dimension is placed on a 0–5 ladder. The level is derived from the
LLM's evidence interpretation and then mapped to Coverage:

| Level | Label | What the evidence must show | Coverage |
|-------|-------|-----------------------------|----------|
| 0 | No Governance Intent | No treatment, or only a passing acknowledgment with **no proposed action** | **Missing** |
| 1 | Governance Recognised | An **explicit commitment or attempted mechanism** (even weak: "will establish guidelines", "commits to…") | Partial |
| 2 | Institutional Ownership Identified | A specific body, office, or role charged with responsibility | Partial |
| 3 | Implementation Commitment Exists | Named body / programme / initiative / roadmap / mandate | **Covered** |
| 4 | Operational Mechanisms Established | Concrete processes, standards, obligations, oversight | Covered |
| 5 | Continuous Monitoring & Enforcement | Active oversight, enforcement powers, audit cycles, redress | Covered |

`LEVEL_TO_COVERAGE = {0: Missing, 1: Partial, 2: Partial, 3: Covered, 4: Covered, 5: Covered}`.

### Rule R1 — the "explicit commitment" floor (Missing → Partial)

Fires when the raw verdict is **Missing** but the document shows evidence of
an **actual attempted mechanism or explicit commitment** — even a weak one.
The trigger is detected deterministically from **any** of:

1. a non-empty operational-mechanism report (named body, reporting
   requirement, enforcement/redress), or
2. a strong commitment phrase in the document chunks (`will establish`,
   `setting up`, `roadmap`, `programme`, `initiative`, `task force`, …), or
3. an explicit commitment verb (`commits to`, `pledge`, `plans to`,
   `intends to`, `will ensure`, `working towards`, …).

Note: `will support` / `will promote` are the weakest floor triggers — a
sentence like "the ministry will support research into AI fairness" is
enough to floor Missing → Partial. That is intentional (the floor is a
low, honest bar: the document proposes real action, however early), but
they are the most permissive entries in the detector.

**What this rule does NOT do:** a bare risk acknowledgment with **no proposed
action attached** (e.g. a sentence that merely mentions the dimension's risk
with no commitment, body, or programme) does **not** satisfy R1 and stays
**Missing**. "Mentioned once" and "genuinely partial" are deliberately kept
apart: Partial now means *the document proposes real action, however early*.

### Rule R2 — the implementation-commitment raise (Partial → Covered)

Fires when the verdict is **Partial** and the document shows a **concrete
implementation commitment** (never directly on a Missing verdict — R1 is the
only rule that rescues Missing), from **any** of:

1. an operational mechanism in the model's report (named body / reporting /
   enforcement-redress), or
2. a single strong commitment phrase in a document chunk (`will establish`,
   `programme`, `initiative`, `roadmap`, `task force`, `mandatory`, …), or
3. weak commitment phrases (`commitment`, `mandate`, `dedicated`, `budget`)
   corroborated by a named-body keyword in the same chunk, or by appearing in
   at least two distinct chunks.

### The three-way outcome

| Raw verdict | R1 fires? | R2 fires? | Final coverage | Meaning |
|-------------|-----------|-----------|----------------|---------|
| Missing | No | No | **Missing** | Bare acknowledgment or nothing at all |
| Missing | Yes | No | **Partial** | Explicit commitment / attempted mechanism, not yet concrete |
| Missing | Yes | Yes | **Covered** | R1 raised to Partial, then R2 raised to Covered on a concrete commitment |
| Partial | — | No | Partial | Genuinely partial, no implementation commitment |
| Partial | — | Yes | **Covered** | Concrete implementation commitment exists |

### Configuration

Set `LADDER_FLOOR_ENABLED=0` to disable the R1 floor entirely: Missing is
never raised to Partial by commitment/acknowledgment alone, and because R2
only operates on Partial verdicts, such dimensions stay **Missing** — this is
the honest "no floor" baseline used for before/after comparisons of floor
impact. R2 cannot be disabled — it is the core anti-under-crediting safeguard
for genuinely Partial dimensions.

The flag is read **at module import time** (backend startup) — toggling it in
a running process has no effect until the backend is restarted.

---

## RAGAS Evaluation

RAGAS metrics measure retrieval and generation quality. Results are reported per metric, not as one aggregate score.

| Metric | Score | Interpretation |
|--------|-------|----------------|
| Faithfulness | *TBD* | Proportion of generated claims that are supported by the retrieved context |
| Answer Relevancy | *TBD* | How relevant the generated answer is to the question |
| Context Precision | *TBD* | How much of the retrieved context is actually relevant |
| Context Recall | *TBD* | How much of the required context was actually retrieved |

To run the evaluation:
```bash
cd backend
python eval/ragas_eval.py
```

*Scores are populated after the first run with indexed frameworks and a running Ollama instance.*

---

## System Limitations

- **Dense retrieval only** — no hybrid (BM25 + embedding) search. Pure embedding similarity means exact keyword matches are not prioritized.
- **Local LLM** — Qwen 3 8B via Ollama is competent but significantly less capable than Claude or GPT-4 for nuanced policy analysis. Upgrade path: swap `LLMService` for an OpenAI/Anthropic provider.
- **Chunk size** — ~1000 tokens with 15% overlap, tuned for legal/policy prose. Very long clauses (>2000 tokens) may lose context.
- **Async via BackgroundTasks** — FastAPI BackgroundTasks are adequate for portfolio scale but not for production. Lost tasks on server restart. Upgrade: Celery + Redis.
- **Scanned PDFs** — No OCR support. Scanned image PDFs are detected and flagged, but not processed. Use with text-layer PDFs only.
- **Non-English documents** — Tested with English-language documents only. Other languages will have degraded retrieval quality with `bge-small-en-v1.5`.
- **No authentication** — No user/auth layer. Intended for portfolio demonstration, not production deployment.

---

## Known Failure Modes

| Scenario | Behavior |
|----------|----------|
| Heavily scanned document | Detection → explicit OCR warning, analysis not attempted |
| Very long document (>100 pages) | Processed but may hit LLM context limits per dimension query |
| Non-English document | Retrieved, but embedding similarity degrades |
| Password-protected PDF | Rejected at validation layer with specific error message |
| Corrupted/incomplete PDF | Rejected at validation layer with specific error message |
| Empty PDF (no text layer) | Rejection with specific error message |
| File > 25MB | Rejected with size limit explicitly stated |
| Off-topic query ("hello", "tell me a joke") | Guardrails reject with scope message before LLM call |
| Query with no retrieval results | Guardrails return "insufficient evidence" — LLM is never called |
| LLM generates low-confidence answer | Surface confidence score and method; flag as insufficient evidence |

---

## Future Roadmap

### Planned upgrades (in priority order):
1. **Celery + Redis** — production-grade async task queue (documented as the planned Celery upgrade from current BackgroundTasks)
2. **Cloud LLM support** — Anthropic Claude / OpenAI provider in `LLMService`
3. **Hybrid retrieval** — BM25 + embedding fusion for better recall
4. **OCR pipeline** — Tesseract integration for scanned document support
5. **Authentication** — API key / OAuth-based access control

### Deferred features (not built in v1 — listed here to show deliberate scope):
- **Timeline Generator** — deferred, not yet approved
- **Stakeholder Mapping** — cut, too easily faked/generic
- **Capacity Building Generator** — original Module 3, deferred
- **SDG Alignment Engine** — original Module 4, deferred
- **Cross-Jurisdictional Comparison** — original Module 6; if revisited, scope to 2 real countries with real ingested documents only
- **Full 6-country Policy Comparison Dashboard** — cut for v1

---

## Testing

```bash
# Unit tests (no external dependencies required)
cd backend
python -m pytest tests/unit/ -v

# Integration tests (requires running services + Ollama)
RUN_INTEGRATION_TESTS=1 python -m pytest tests/integration/ -v

# Evaluation tests (requires indexed frameworks)
RUN_EVALUATION_TESTS=1 python -m pytest tests/evaluation/ -v
```

### Test coverage

| Area | Coverage | Notes |
|------|----------|-------|
| Upload validation | 6 failure modes individually tested | File type, size, corruption, password, empty, OCR-detection |
| Chunking | Structure-aware split + recursive split behavior | Overlap correctness, metadata propagation |
| Citation verification | chunk_exists, page_exists, text_supports_claim | Including deliberately broken cases |
| Guardrails | Greeting rejection, off-topic rejection, no-retrieval, low-similarity | |
| Brief generator | Text brief sections | |
| Workspace status | Enum transitions, state comparisons | |
| Integration | Upload → ingest → retrieve → analyze → brief | Full pipeline with real small doc |
| Evaluation | Retrieval quality per dimension | Requires indexed frameworks |

---

## Project Structure

```
aura-sdg/
├── config/
│   └── frameworks.yaml           # Config-driven framework definitions
├── backend/
│   ├── data/
│   │   ├── raw_policies/         # Ingested PDFs
│   │   ├── chroma/               # ChromaDB persistence (gitignored)
│   │   └── uploads/              # Uploaded policy PDFs
│   ├── src/
│   │   ├── ingestion.py          # Document parsing + structure-aware chunking
│   │   ├── validation.py         # PDF validation (type, size, password, empty, OCR)
│   │   ├── vectorstore.py        # ChromaDB + embeddings + dense retrieval
│   │   ├── gap_analyzer.py       # RAG agent with full enriched Pydantic schema
│   │   ├── brief_generator.py    # Executive brief text export
│   │   ├── verify.py             # Citation verification (chunk, page, text support)
│   │   ├── workspace.py          # Country Office Workspace data model
│   │   ├── guardrails.py         # Off-topic/greeting rejection, out-of-corpus handling
│   │   ├── framework_sync.py     # Config-driven sync from official PDF URLs
│   │   ├── framework_library.py  # Framework Library metadata/indexing status
│   │   ├── tasks.py              # Background analysis pipeline
│   │   ├── db_models.py          # PostgreSQL ORM models
│   │   └── logging_config.py     # Structured JSON logging
│   ├── eval/
│   │   ├── test_questions.json   # 15 hand-built RAGAS test questions
│   │   └── ragas_eval.py         # RAGAS evaluation script
│   ├── tests/
│   │   ├── unit/                 # Upload validation, chunking, citation verify, guardrails
│   │   ├── integration/          # End-to-end pipeline tests
│   │   └── evaluation/           # Retrieval quality checks
│   ├── main.py                   # FastAPI app with /api/v1/ routes
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── workspace/            # Country Office Workspace
│   │   ├── analysis/             # Gap analysis + Explainability Chain
│   │   ├── brief/                # Executive Brief export
│   │   ├── frameworks/           # Framework Library
│   │   └── page.tsx              # Landing/home
│   ├── components/               # StatusBadge, RiskTag, CitationCard
│   ├── lib/
│   │   └── api.ts                # Typed API client
│   ├── Dockerfile
│   ├── package.json
│   └── tsconfig.json
├── docker-compose.yml            # v1: api, web, postgres
├── .env.example
├── .gitignore
└── README.md
```

---

## Deployment (Intended)

| Service | Target | Notes |
|---------|--------|-------|
| API backend | Render | FastAPI as a web service |
| Frontend | Vercel | Next.js static export or serverless |
| Database | Render PostgreSQL or Supabase | PostgreSQL-compatible |
| Vector store | ChromaDB bundled with API | Embedded persistence on Render disk |

**Current deployment status:** Docker Compose for local development. The frontend points to `http://localhost:8000/api/v1` by default — configure via `NEXT_PUBLIC_API_URL`.

---

## Design Principles

- **Honest output** — every claim in the UI is backed by real pipeline state. No hardcoded demo data. No templated answers dressed up as analysis.
- **Verified citations** — every cited chunk is programmatically checked (exists, page matches, text supports claim). Unverifiable citations are discarded and replaced with "insufficient evidence."
- **No training-data answers** — the LLM only answers from retrieved context. If the context doesn't contain the answer, the system says so.
- **Testable modules** — every file in `src/` is independently unit-testable without spinning up the full pipeline.
- **Clean separation** — the backend has zero knowledge of the frontend. All communication is HTTP/JSON.

---

## Confidence Score

Each governance gap includes a `confidence_score` (float 0–1) and a `confidence_method` string explaining how it was computed.

**Formula:**

1. Collect all `similarity_score` values from the retrieved evidence chunks (cosine similarity between chunk embedding and query embedding, range 0–1).
2. `base = mean(similarity_scores)` — average similarity of all retrieved chunks for that dimension.
3. If `citation_pass_rate` is provided (from citation verification):
   `confidence = base × (0.5 + 0.5 × citation_pass_rate)`
   where `citation_pass_rate = passes / (passes + fails)`. A 100% pass rate leaves confidence at the base value; a 0% pass rate halves it.
4. If no citation data is available: `confidence = base`.
5. Clamped to [0.0, 1.0].

The `confidence_method` field reports the exact inputs used (mean similarity, score range, citation pass rate if blended).

Confidence is computed from actual retrieval data, not from an LLM self-assessment.
