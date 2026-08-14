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

## 3. Option B — Vercel (frontend) + VPS/Render (API)

The frontend is **fully static** (all routes prerendered, no server data
fetching), so it can live free on Vercel/Netlify with zero server cost:

```bash
# Frontend (on your dev machine, in aura-sdg/frontend)
NEXT_PUBLIC_API_URL=https://api.example.com/api/v1 npm run build
npx vercel --prod          # or: npx netlify deploy --prod
```

Backend still needs a real always-on host with persistent disk (see Option A
for the VPS, or Render with a **paid** plan — see below). Point
`CORS_ORIGINS` at the frontend origin.

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
