# LAUNCH — Meridian (AI Policy Intelligence Workbench)

This document covers deploying the three pieces: **frontend** (Next.js), **API**
(FastAPI), and **Postgres** — plus the two data assets that *cannot be
recreated* and must be shipped with the app.

---

## 0. What cannot be recreated

- **`backend/data/chroma` (711 MB)** — the indexed corpus: 33 frameworks,
  53k+ chunks. Much of it was ingested from local Downloads files (Singapore,
  NESCO, World Bank, environment toolkit, …) that have **no public URL**, so a
  fresh server **cannot re-sync it**. Ship it.
- **`backend/data/uploads` (306 MB)** — uploaded policy PDFs referenced by
  existing analyses. Ship it if you want history to work; empty is fine for a
  clean start.

Everything else (Postgres, images, code) is rebuildable.

---

## 1. Required environment variables

Copy `backend/.env` → `.env.prod` and adjust:

| Var | Value in production |
|---|---|
| `DATABASE_URL` | overridden by compose to the `postgres` service — keep the local value, compose wins |
| `GEMINI_API_KEY` + `GEMINI_API_KEY_2/3/4` | your real keys (already in `backend/.env`) |
| `LLM_PROVIDER` | `gemini` |
| `GEMINI_MODEL` | as configured |
| `CORS_ORIGINS` | the browser origin(s), e.g. `https://meridian.example.com` (same-origin via caddy needs nothing; set it if frontend and API live on different domains) |
| `LOG_LEVEL` | `INFO` |
| `DEV_MODE` | `false` (compose forces this) |
| `CHROMA_PERSIST_DIR` | `/app/data/chroma` (compose forces this) |

Compose-level vars for `.env.prod` (root of `aura-sdg/`):

| Var | Meaning |
|---|---|
| `NEXT_PUBLIC_API_URL` | Public backend URL **inlined at frontend build time**, e.g. `https://meridian.example.com/api/v1` |
| `SITE_ADDRESS` | Domain for Caddy TLS, e.g. `meridian.example.com` (omit for `localhost` test) |

---

## 2. Option A — Single VPS with Docker Compose (recommended)

Best fit: the API runs long in-process background tasks (2–5 min analyses),
needs ~3–4 GB RAM (NLI cross-encoder + embeddings + ChromaDB + Postgres), and
persistent disk. A $4–8/mo VPS beats every free-tier host for this workload.

**Requirements:** ~4 GB RAM, ~30 GB disk, Docker + compose.

```bash
# 1. On the server: install docker + compose, clone/copy the repo
#    (or scp the aura-sdg/ folder).

# 2. Ship the corpus + uploads (from your dev machine):
rsync -avz backend/data/ user@server:/path/to/aura-sdg/backend/data/

# 3. On the server, create .env.prod from backend/.env (see section 1)
cp backend/.env .env.prod
#    ... then edit .env.prod: add NEXT_PUBLIC_API_URL and SITE_ADDRESS

# 4. Build & start
docker compose -f docker-compose.prod.yml up -d --build

# 5. Point your DNS A record at the server IP. Caddy auto-issues TLS.
```

Notes:
- First start is slow: the API image installs `sentence-transformers`
  (~150 MB of models download at first request) and the NLI
  `cross-encoder/nli-deberta-v3-base` (~1.5 GB) — allow the 90 s healthcheck
  `start_period`.
- Logs: `docker compose -f docker-compose.prod.yml logs -f api`.
- Backups: snapshot the `chroma_data`, `uploads_data`, `pgdata` volumes.
- **Security**: there is **no auth layer** — anyone with the URL can upload,
  run analyses, and burn your Gemini quota. Until auth is built, either
  keep the site private (basic auth in Caddy) or accept the exposure.

---

## 3. Option B — Vercel (frontend) + always-on API host (the split architecture)

This is the architecture: Vercel serves the dashboard, the API runs on an
always-on host, and the frontend polls for job completion.

```
Vercel (frontend — free, static)
  │  POST /upload/{workspace_id}          <- the "POST /analyses"
  ▼
FastAPI (always-on host)
  ├── saves the PDF, queues the background worker
  └── returns {status: "processing"}     <- job_id = workspace_id, immediate
          ▼
     Background worker (in-process)
    ┌───────┬──────────┬────────┐
    ↓       ↓          ↓        ↓
  Ingest  Retrieval  Gemini   Verify
    │       │          │        │
    └───────┴──────────┴────────┘
          ▼
      PostgreSQL (hosted)
          ▼
        COMPLETE
          │
          ▼
Vercel polls /workspace + /analyze/{id} every 3s  ->  dashboard
```

The good news: **this flow already exists in the code.** The workspace page
polls every 3s while any workspace is `queued`/`processing`/`generating_report`;
`POST /upload/{id}` returns immediately with `{status: "processing"}`; status
lives in Postgres so polling is instance-agnostic. You are wiring hosting, not
rewriting.

### 3a. Frontend → Vercel (free)

```bash
cd frontend
# Build with the production API URL baked in
NEXT_PUBLIC_API_URL=https://api.your-domain.com/api/v1 npx vercel --prod
```

- All routes are client-side/static — Vercel serves them as-is (`output:
  standalone` is ignored by Vercel's own builder; no config change needed).
- Every deploy must set `NEXT_PUBLIC_API_URL` (it is inlined at build time).

### 3b. API + worker + corpus → an always-on host

The API **cannot** live on Vercel: analyses run 2–5 min in-process, far past
serverless limits. It needs a host that never sleeps and has persistent disk
for the corpus. Pick one:

| Host | Cost | Corpus disk | Sleeps? | Notes |
|---|---|---|---|---|
| **Railway** | ~$5/mo + ~$0.30 volume | volume mount | no | easiest volumes; single service |
| **Render** (web) | $7/mo + ~$0.50 disk | persistent disk add-on | no | plus Postgres $7 (free tier expires in 30 days) |
| **Fly.io** | ~$8–12/mo | volume | no | needs 2–4 GB RAM machine |
| **VPS** (Hetzner/DO) | €4–6/mo | 40 GB built-in | no | cheapest; runs Postgres too (Option A) |

Free tiers (Render/Fly) **sleep after idle** — sleeping kills in-flight
analyses and the background task, so they are not viable for the API.

**Ship the corpus** (once, to the host's persistent disk):

```bash
rsync -avz backend/data/ user@host:/path/to/aura-sdg/backend/data/
```

`backend/data` = chroma index (697 MB, the frameworks) + `uploads/` (your
policy PDFs). If you committed the 5 local-only framework PDFs to the repo, a
fresh host can also rebuild chroma from them, but shipping the index is
faster and deterministic.

**Postgres:** hosted (Neon/Supabase/Render Postgres) via `DATABASE_URL`, or on
the VPS itself.

### 3c. Environment on the API host

| Var | Value |
|---|---|
| `GEMINI_API_KEY` (+ `_2/_3/_4`) | your keys |
| `LLM_PROVIDER` | `gemini` |
| `DATABASE_URL` | hosted Postgres connection string |
| `CORS_ORIGINS` | `https://<your-app>.vercel.app` (or custom domain) |
| `CHROMA_PERSIST_DIR` | path to the shipped `backend/data/chroma` |
| `DEV_MODE` | `false` |

### 3d. Verify

- [ ] `curl https://api.your-domain.com/api/v1/health` → 200 with framework count
- [ ] Frontend loads from Vercel; create a workspace; upload a PDF
- [ ] Watch status `queued → processing → complete` in the dashboard
- [ ] Analysis finishes and citations show `verified`

**Honest caveats:** the background worker is in-process (`BackgroundTasks`) —
if the API host restarts mid-analysis, the workspace stays `processing` until
you re-trigger it (per-dimension results are saved incrementally, so a re-run
resumes, not restarts). A Celery + Redis queue is the upgrade if you ever run
multiple instances. And there is **no auth layer** — protect the API with
Caddy basic auth or an API key until auth is built.

---

## 4. Option C — Render (README's original intent) — with caveats

Render's **free tier is not suitable** for this app:
- Free web services **sleep after 15 min idle** — in-flight analyses (2–5 min
  background tasks) die on sleep, and every wake/recycle loses ephemeral disk.
- The Chroma corpus + uploads (1.2 GB) need a **persistent disk add-on**
  (paid) or an external volume.
- API web service (Python 3.12, 2 GB+ RAM for the models), Render Postgres,
  and the frontend as a static site.

Workable but roughly $7–19/mo for the API + disk — at which point the VPS
(Option A) is simpler and cheaper. If you go this route: no Dockerfile
changes needed, set the same env vars from section 1 in the Render dashboard,
and mount the disk at `/opt/render/project/src/backend/data`.

---

## 5. Verification checklist

- [ ] `curl https://<domain>/api/v1/health` → 200 with vector store status
- [ ] `curl https://<domain>/api/v1/frameworks` → 33 frameworks, all indexed
- [ ] Home page loads; create a workspace; upload a PDF; analysis completes
- [ ] `docker compose ... logs api` shows no 429 storm / startup errors

---

## 6. Current production-readiness fixes (this session)

- `backend/main.py` — CORS origins now env-driven (`CORS_ORIGINS`), no longer
  hardcoded to localhost.
- `backend/Dockerfile` — removed `--reload` (dev flag); image now runs
  production uvicorn.
- `backend/.dockerignore`, `frontend/.dockerignore` — keep `.env` secrets,
  dev data, and caches out of the images.
- `frontend/Dockerfile` — `NEXT_PUBLIC_API_URL` build arg (was silently
  defaulting to `localhost:8000` in the image).
- `docker-compose.prod.yml` — production compose: no source mounts, restart
  policies, persistent volumes (chroma/uploads/postgres), healthchecks,
  optional Caddy TLS reverse proxy.

**Still open before launch:** Docker is not installed on this machine, so the
images have not been built/run here — first `docker compose up` on the server
is the real smoke test. And there is no auth layer (see security note above).
