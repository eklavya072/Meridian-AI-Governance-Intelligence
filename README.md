<div align="center">

# Meridian

**Evidence-grounded analysis of national AI governance policy**

[![CI](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/ci.yml)
[![Release](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/release.yml/badge.svg)](https://github.com/eklavya072/Meridian-AI-Governance-Intelligence/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Live demo](https://img.shields.io/badge/live%20demo-open-2e7d32.svg)](https://meridian-ai-governance.duckdns.org)

**[Live demo](https://meridian-ai-governance.duckdns.org)** · [How it works](#how-it-works) · [Results](#results) · [Engineering](#engineering-and-operations) · [Run it locally](#run-it-locally) · [Documentation](#documentation)

</div>

---

Meridian reads a national AI policy (a strategy, a set of guidelines, a draft
bill) and produces a brief that sets out, for eight governance dimensions,
what the document actually requires and what it leaves open. Every finding
points to the passage it rests on, so a reader who disagrees can check the
source.

It is built for the analyst who has to answer a practical question about a
policy text: *does this document commit anyone to anything, and where are the
gaps?*

> **Scope.** Meridian assesses only the documents it is given, never a
> country's governance system as a whole, and it does not rank countries.
> Breadth and binding force are reported as two separate measures rather than
> combined into a single score.

Meridian is built as a production service. Every change is tested in a
container that shares the production image's layers, every release is scanned
for vulnerabilities and published as a public multi-architecture image, and
the service ships with tracing, a runbook and rehearsed zero-downtime
rollback. See [Engineering and operations](#engineering-and-operations).

## Try it

The **[live demo](https://meridian-ai-governance.duckdns.org)** includes
worked analyses for eight jurisdictions, **China, Egypt, the European Union,
India, Japan, Kenya, Rwanda and the United Kingdom**, as read-only examples.
You can also create a workspace, upload a policy PDF and run a new analysis
(model access on the demo is rate-limited).

## Why it matters

National AI policies are often compared by the topics they mention. A
strategy that devotes a chapter to privacy and a statute that creates
enforceable privacy duties both appear to "address privacy", which makes such
comparisons close to uninformative. Meridian separates what a document
*mentions* from what it *requires*: who is obliged, how firmly, and with what
consequence.

Country-level assessments, such as UNDP's AI Landscape Assessment and
UNESCO's Readiness Assessment Methodology, examine a country's whole AI
ecosystem through research and consultation. Meridian works one level down,
on the text of individual policy instruments. It can support that kind of
assessment; it is not a substitute for it.

## Reference frameworks

Findings are aligned to **43 reference instruments**, listed with their
sources in [`config/frameworks.yaml`](config/frameworks.yaml) and on the
demo's Framework Library page. They include:

| | |
|---|---|
| **United Nations** | UNESCO Recommendation on the Ethics of AI · UN Global Digital Compact · UN Roadmap for Digital Cooperation · UNDP Digital Strategy 2022–2025 · UNESCO Policy Area 5 (Environment and Ecosystems) |
| **Multilateral and regional** | OECD AI Principles · African Union Continental AI Strategy · ASEAN Guide on AI Governance and Ethics · World Bank Digital Progress and Trends Report 2025 |
| **Regulatory and technical** | EU AI Act (Regulation (EU) 2024/1689) · NIST AI Risk Management Framework 1.0 · NIST SP 1270 (bias in AI) |

Which instruments are consulted is decided in code, never by the model. Core
normative sources are always searched, dimension-specific sources are
guaranteed a place for their dimension, and regional frameworks are added by
country: a policy from an African Union member state is also read against the
African Union strategy, and one from an ASEAN member against the ASEAN guide.

## What an analysis produces

Each document is assessed on eight governance dimensions, covering 45
expected governance mechanisms in total.

| Dimension | What is assessed |
|---|---|
| Transparency | Disclosure of AI capabilities and limitations; explainability |
| Accountability | Allocation of responsibility, liability, oversight and redress |
| Privacy | Data protection, consent, anonymisation and security |
| Safety | Risk identification, impact assessment, testing and incident monitoring |
| Human Autonomy | Human control, human-in-the-loop and the right to human review |
| Inclusivity | Equitable access, non-discrimination and accessibility |
| Fairness | Bias testing and mitigation, and inclusive design |
| Environmental Sustainability | Energy efficiency, carbon reporting and e-waste management |

For every dimension, the analysis gives:

- **A coverage verdict:** Covered, Partial or Missing.
- **An implementation depth stage:** Unaddressed, Emerging, Delegated, Operationalized or Institutionalized.
- **The evidence behind it:** how many provisions were read, how many bind, and how many carry a consequence.
- **Recommendations** aligned to the reference frameworks, with good practice and international examples where a dimension is already covered.
- **An implementation roadmap** for open dimensions, with a responsible agency taken from the document itself and never supplied by the model.
- **Relevant real-world cases**, from sources such as the AI Incident Database, the Robodebt Royal Commission and the Allegheny Family Screening Tool evaluation, when a genuine match exists.

The results are gathered into an **executive brief**, exportable as PDF or
DOCX, and the **AI Auditor** answers follow-up questions about an analysis or
the framework library, with verified citations.

## How it works

```
Policy PDF
  → validation            file type, size, encryption, scanned-image detection
  → preparation           structure-aware chunking, embeddings (BAAI/bge-small-en-v1.5)
  → retrieval             per dimension: dense + BM25, reciprocal rank fusion
  → scoring        (code) normative force of every operative sentence
  → verdicts       (code) coverage, implementation depth, priority
  → mechanism check (LLM) does each provision establish the mechanism? can only lower a result
  → explanation     (LLM) reasoning and recommendations for the fixed verdict
  → verification          every citation: passage exists · page matches · text is consistent
  → roadmap and cases → executive brief → PDF / DOCX
```

The method rests on five rules.

- **Force, not topic.** Every operative sentence in the supplied text is
  graded on a five-tier normative-force ladder (*Aspirational, Intentional,
  Assigned, Obligatory, Enforceable*) according to whom it addresses, how
  firmly it is worded, and what consequence attaches to it. The ladder follows
  Abbott and Snidal's legalization framework of obligation, precision and
  delegation. Recitals, definitions and headings are excluded, and the whole
  text is read rather than a sample.
- **Verdicts are computed, then explained.** Coverage, implementation depth,
  priority, roadmap timelines and responsible agencies are derived in code
  from the graded provisions. The language model is given the verdict as a
  fixed input and writes the explanation; it never sets a verdict. It is
  consulted once on the verdict path, to confirm that a provision really
  establishes a mechanism, and it can only lower a result. If that check is
  unavailable, the run is marked provisional.
- **Two measures, never one.** Breadth (how many of a dimension's expected
  mechanisms the text reaches) and depth (how firmly those provisions bind)
  are reported side by side, because the informative cases are where they
  diverge: a narrow statute that binds hard, or a broad strategy that binds
  nobody.
- **Every citation is checked.** Each cited passage is verified three ways:
  it exists, its page matches, and the quoted text is consistent with the
  source. Where nothing supports a claim, the output says so instead of
  inventing a citation, and an institution is named only if the document
  itself names it.
- **Reproducible.** The test suite replays complete analyses against
  recorded model responses and asserts that verdicts are identical across runs
  and that every citation resolves.

## Results

| Measure | Result |
|---|---|
| Worked examples | 8 jurisdictions: China, Egypt, European Union, India, Japan, Kenya, Rwanda, United Kingdom |
| Reference library | 43 instruments, 8,687 indexed passages |
| Citations verified at source | **318 of 330 (96.4%)** across the eight worked examples |
| Automated tests | **1,395 passing**, 82% line coverage (CI gate: 80%) |
| End-to-end analysis | **78.9 s** from upload to exported PDF brief (one live run, 11 model calls) |

How each figure was measured, with dates and conditions, is recorded in
[docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

## Engineering and operations

Meridian is built to be deployed and run, not only demonstrated. The service
objective it watches most closely is citation quality rather than uptime:
outages are visible, but a quiet drop in citation quality would put an
indefensible brief in front of a policy analyst. Everything below is measured, with
conditions and dates in [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md).

| Area | Measured |
|---|---|
| Test suite | **1,395 tests passing**, 82% line coverage; CI fails below 80% |
| Continuous integration | Four jobs on every change: lint, types and tests; the tests again **inside a container built from the production image's layers**; the full stack from a clean clone; the web app build |
| Release pipeline | About **4 minutes**, with `linux/amd64` and `linux/arm64` built in parallel on native runners and published as one public image |
| Release security | Every release is **blocked by any fixable high or critical vulnerability** (Trivy) and ships with an SPDX 2.3 software bill of materials (235 packages in v1.0.0) |
| Container image | 1,882 MB and CPU-only: about two-thirds smaller than the default build, by excluding a GPU runtime the service never uses. CI asserts that it runs as a **non-root user** and carries **no build tooling** |
| Zero-downtime deployment | Rollout and rollback in **8.8–9.4 s**, with **0 of 921** health probes failing across three drills |
| Load test (k6, replay mode) | **207 of 207 checks passed, 0 server errors**; work beyond capacity refused at once with HTTP 429 rather than queued (36 of 81 runs); end-to-end p50 4.9 s, p95 6.9 s |
| Live end-to-end run | **78.9 s** from upload to exported PDF brief; 11 model calls; all 39 evidence items verified |
| Provider-failure drill | Quota exhaustion detected after 9 failed calls, readiness reports `503`, and recovery is automatic |

**Delivery.** `make` is the single entry point for every task, from `make up`
to `make rollout`, and dependencies are locked (`uv.lock`). The tests run in
a container that shares every layer beneath it with the production image, so
CI tests what actually ships. Deployments switch image digests with no
downtime ([`deploy/rollout.sh`](deploy/rollout.sh)). Liveness (`/healthz`) and
readiness (`/readyz`) are separate checks: readiness reports `503` when a
dependency such as the model provider is unavailable, and a deployment waits
for it before switching traffic.

**Security.** The release gate has no suppressed findings (`.trivyignore`
lists none), and the production image runs as a non-root user with no
compilers or package managers in its runtime layer. Secrets come from the
environment, the operator-only re-index endpoint requires `ADMIN_TOKEN`, and
TLS is terminated by Caddy, whose configuration includes an optional
basic-authentication block.

**Observability.** Each analysis is a single OpenTelemetry trace with a span
per pipeline stage, and its trace ID appears on every structured log line.
Prometheus metrics feed a Grafana dashboard provisioned from a
[committed file](observability/grafana/dashboards/meridian.json), covering
citation pass rate, verdict distribution, per-stage latency and provider
failover ([screenshot](docs/img/grafana-dashboard.png)). `make observability`
brings up Prometheus, Grafana and Jaeger locally.

**Operations.** The [runbook](docs/RUNBOOK.md) sets four service objectives
(availability, successful-analysis rate, analysis latency and citation pass
rate) and five failure modes, each with detection, diagnosis, response and
recovery. [INCIDENT-001](docs/INCIDENT-001.md) records a controlled drill of
provider-quota exhaustion: what the signals showed and what was changed.

**Resilient model access.** Calls to the model are rate-limited per minute and
capped per day, with the daily count kept across restarts. They retry with
jittered backoff and honour the delay the provider asks for, and each
credential sits behind a circuit breaker that recovers on its own. Admission
control refuses work beyond capacity immediately instead of letting it queue.

**Storage.** Uploads go to the local filesystem or to Azure Blob Storage. The
development stack runs the Azurite emulator, and the Azure Blob integration
tests run in CI against it.

## Run it locally

**Requirements:** Docker with Compose v2 (or [uv](https://docs.astral.sh/uv/)
and Node 20+ for development) and a Google Gemini API key; the free tier is
enough.

```bash
git clone https://github.com/eklavya072/Meridian-AI-Governance-Intelligence.git
cd Meridian-AI-Governance-Intelligence
cp .env.example .env        # add your GEMINI_API_KEY
make up && make ready       # starts the stack and waits until it is ready
```

The web app is then at `http://localhost:3000`, and the API at
`http://localhost:8000`, with interactive documentation at `/docs`.

<details>
<summary><b>Common commands</b></summary>

| Command | What it does |
|---|---|
| `make setup` | Install the locked Python dependencies and the frontend packages |
| `make up` / `make down` | Start or stop the stack (volumes are kept) |
| `make ready` | Wait until `/readyz` reports every dependency healthy |
| `make test` | Run the test suite with the coverage gate |
| `make test-container` | Run the test suite inside the built production image |
| `make check` | Lint, type-check and test, in the same order as CI |
| `make observability` | Start Prometheus, Grafana and Jaeger with tracing enabled |
| `make bench` | Re-measure citation verification (no model calls) |
| `make deploy` / `make rollout` | Start the production stack / replace the API without downtime |

Run `make` with no arguments for the full list.

</details>

<details>
<summary><b>Configuration</b></summary>

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | none | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model for every language-model call |
| `GEMINI_RPM_LIMIT` / `GEMINI_RPD_LIMIT` | `3` / off | Requests per minute per credential; optional daily cap |
| `DATABASE_URL` | local PostgreSQL | PostgreSQL connection string |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | Location of the vector store |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed browser origins |
| `BATCH_EVALUATION` | `0` | `1` evaluates all dimensions in one call (fewer requests, fewer citations) |
| `ANALYSIS_MAX_CONCURRENCY` | `3` | Parallel dimension workers |
| `ADMIN_TOKEN` | unset | Required for the framework re-index endpoint |
| `LOCKED_WORKSPACE_IDS` | unset | Read-only example workspaces on a public deployment |

The full set, with explanations, is in [`.env.example`](.env.example).

</details>

<details>
<summary><b>API</b></summary>

All endpoints are under `/api/v1`; interactive documentation is at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Service health and vector-store status |
| `GET` | `/frameworks` | The reference library, with indexing status |
| `POST` | `/workspace` | Create a workspace (country and policy title) |
| `GET` | `/workspace` · `/workspace/{id}` | List or fetch workspaces |
| `POST` | `/upload/{workspace_id}` | Upload a policy PDF |
| `POST` | `/analyze/{workspace_id}/run` | Analyse every uploaded document, in the background |
| `GET` | `/analyze/{workspace_id}` | Runs for the workspace and the latest complete result |
| `POST` | `/brief/{workspace_id}/generate` | Generate the executive brief |
| `GET` | `/brief/{workspace_id}/export?format=pdf\|docx` | Export the brief |
| `POST` | `/chat` | Ask the AI Auditor a question |

```bash
# Create a workspace, upload a policy, run the analysis, export the brief
curl -X POST http://localhost:8000/api/v1/workspace \
  -H "Content-Type: application/json" \
  -d '{"country": "India", "policy_title": "National AI Strategy"}'
curl -X POST http://localhost:8000/api/v1/upload/{workspace_id} -F "file=@policy.pdf"
curl -X POST http://localhost:8000/api/v1/analyze/{workspace_id}/run
curl -X POST http://localhost:8000/api/v1/brief/{workspace_id}/generate
curl -o brief.pdf "http://localhost:8000/api/v1/brief/{workspace_id}/export?format=pdf"
```

</details>

<details>
<summary><b>Project structure</b></summary>

```
Meridian/
├── backend/
│   ├── main.py                    FastAPI application
│   ├── src/
│   │   ├── validation.py          PDF checks: type, size, encryption, scanned pages
│   │   ├── ingestion.py           parsing, text repair and structure-aware chunking
│   │   ├── hybrid_search.py       dense + BM25 retrieval with reciprocal rank fusion
│   │   ├── framework_router.py    which reference instruments each dimension consults
│   │   ├── evidence_strength.py   normative-force ladder, mechanisms, coverage and depth
│   │   ├── gap_analyzer.py        per-dimension orchestration; where verdicts are set
│   │   ├── verify.py              citation verification
│   │   ├── brief_synthesis.py     executive brief; brief_export.py renders PDF / DOCX
│   │   ├── chat.py                the AI Auditor
│   │   └── provider_router.py     model access: rate limits, backoff, daily quota
│   └── tests/                     unit, integration, evaluation and replay suites
├── frontend/                      Next.js web app
├── config/frameworks.yaml         the 43 reference instruments
├── deploy/                        zero-downtime rollout, demo image and VM setup
├── observability/                 Prometheus and a Grafana dashboard defined as code
├── loadtest/                      k6 load test (replay mode, no model calls)
└── docs/                          runbook, measurements, incident drill
```

</details>

<details>
<summary><b>Testing</b></summary>

```bash
make test             # the suite, with the coverage gate
make test-container   # the same suite inside the built production image
make check            # lint, type-check and test, as CI does
```

The suite keeps all of its state (index, uploads, quota records) in a
temporary directory, so it is safe to run beside a live API. Coverage includes
an evidence gate that replays full analyses against recorded model responses,
pinned readings of the EU AI Act and the UK AI white paper, PDF failure modes,
citation verification including deliberately broken cases, the
normative-force scorer, framework routing and the executive brief.

The 26 skipped tests need external state (running services, an indexed corpus or a Gemini key) and are run on request:

```bash
RUN_INTEGRATION_TESTS=1 make test   # requires running services
RUN_EVALUATION_TESTS=1  make test   # requires an indexed framework corpus
MERIDIAN_LIVE_GATE=1    make test   # makes ten live Gemini requests
```

</details>

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy (async), PostgreSQL 16 |
| Retrieval | ChromaDB, `BAAI/bge-small-en-v1.5` embeddings, BM25 hybrid search |
| Language model | Google Gemini (`gemini-3.5-flash-lite`), with rate limiting, backoff and daily quota accounting |
| Web app | Next.js 14, React 18, TypeScript, Tailwind CSS |
| Delivery | uv, Make, Docker (multi-architecture), GitHub Actions, GitHub Container Registry, Trivy, Syft |
| Operations | Caddy, OpenTelemetry, Prometheus, Grafana, Jaeger, k6, Azure Blob Storage (Azurite locally) |

## Limitations

- **Documents, not countries.** Verdicts describe the supplied text only, not
  the wider legal or institutional system around it.
- **Not a substitute for expert review.** Results come from a documented,
  reproducible procedure, but they have not been validated against expert
  legal assessment. They are meant to inform analysts, not to replace them.
- **English, digital PDFs.** Tuned for English-language documents; scanned,
  image-only PDFs are detected and flagged rather than processed.
- **No user accounts yet.** Suitable for demonstration and team use rather
  than multi-tenant production. The public demo runs on rate-limited model
  access.
- **In-process background jobs.** Restarting the server interrupts an
  analysis that is in progress.

## Documentation

| Document | Contents |
|---|---|
| [LAUNCH.md](LAUNCH.md) | Deployment guide |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations: service-level objectives, failure modes, rollback |
| [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) | How every reported figure was measured |
| [docs/INCIDENT-001.md](docs/INCIDENT-001.md) | A controlled provider-quota failure drill |
| [config/frameworks.yaml](config/frameworks.yaml) | The reference library, with sources |

## Author

Built by **Eklavya Singh** ([github.com/eklavya072](https://github.com/eklavya072)).
Released under the [MIT License](LICENSE).
