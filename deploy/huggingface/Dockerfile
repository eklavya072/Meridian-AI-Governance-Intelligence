# Meridian as a single container, for a Hugging Face Docker Space.
#
# A Space runs exactly one container, so this image holds all three parts:
# Postgres, the API, and the web app as a static export that the API serves
# itself (FRONTEND_DIST). The multi-service stack in docker-compose.yml is
# the production shape; this is the demo shape, and nothing in the
# application differs between them.
#
# The showcase data (the vector index and a database seed with the eight
# country analyses) is not in the code repository. It is pulled at build
# time from a private dataset, using the Space's HF_TOKEN secret.

# ── web: the frontend as plain HTML, CSS and JS ──────────────────────────
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV NEXT_OUTPUT=export \
    NEXT_PUBLIC_API_URL=/api/v1 \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ── app ──────────────────────────────────────────────────────────────────
FROM python:3.13-slim

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libmagic1 postgresql \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

# Spaces run the container as uid 1000.
RUN useradd --create-home --uid 1000 user

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/opt/hf

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# The embedding model, baked in so start-up never waits on the network.
RUN /opt/venv/bin/python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# The showcase index and database seed, from the private dataset.
ARG MERIDIAN_DATA_REPO
RUN --mount=type=secret,id=HF_TOKEN,mode=0444,required=true \
    /opt/venv/bin/python -c "import os; from huggingface_hub import snapshot_download; \
snapshot_download(repo_id=os.environ['MERIDIAN_DATA_REPO'], repo_type='dataset', \
local_dir='/opt/seed', token=open('/run/secrets/HF_TOKEN').read().strip())" \
    && test -f /opt/seed/seed.sql && test -d /opt/seed/chroma

COPY backend/ ./
COPY config/ /opt/config/
COPY --from=web /web/out /opt/web
COPY entrypoint.sh /usr/local/bin/meridian-entrypoint
RUN chmod +x /usr/local/bin/meridian-entrypoint

# Everything the app writes goes under /tmp/meridian: the database, a
# writable copy of the index, uploads and the quota ledger. A Space's disk
# is ephemeral, so each restart comes back to the showcase state.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    FRAMEWORKS_CONFIG_PATH=/opt/config/frameworks.yaml \
    FRONTEND_DIST=/opt/web \
    DATABASE_URL=postgresql+asyncpg://aura@127.0.0.1:5432/aura_sdg \
    CHROMA_PERSIST_DIR=/tmp/meridian/chroma \
    UPLOAD_DIR=/tmp/meridian/uploads \
    PROVIDER_HEALTH_FILE=/tmp/meridian/provider_health.json \
    GEMINI_RPD_FILE=/tmp/meridian/gemini_rpd.json \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=gemini-3.5-flash \
    LOCKED_WORKSPACE_IDS=eecbec2a-5ca7-4246-96a1-5db7b4b85415,f6a1069c-f17a-44a1-b99c-5855b769d6ba,2ab3a4b3-46ed-4dca-a30e-892f5bdb3068,62774187-5910-4b73-9949-6a6106a1dad4,1d44139a-09db-4479-af7f-f7c50e04562d,0193c4ae-4a29-427e-8bfb-7ce8cfc448ae,b5f452c0-8cb0-4855-a3b3-effdc6078069,fd789d63-2f4e-4719-8460-f2b69bc17ae8

USER user
EXPOSE 7860
CMD ["meridian-entrypoint"]
