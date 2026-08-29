# Meridian API — multi-stage build.
#
# Targets:
#   builder — resolves the locked dependency set into /opt/venv
#   test    — builder plus the dev group and the test suite, so CI can run
#             pytest against the same layers the prod image ships
#   prod    — runtime only: no uv, no compilers, no dev group, non-root
#
# Build context is the REPO ROOT, not backend/: the backend reads
# config/frameworks.yaml, which lives outside backend/. With a backend/
# context that file never entered the image and every framework-routing
# call raised FileNotFoundError at runtime.
#
# Python 3.13 matches .python-version and the interpreter uv.lock is resolved
# against. The image previously pinned 3.12 while everything was developed and
# tested on 3.13, which is exactly the drift a lockfile is supposed to remove.

ARG PYTHON_VERSION=3.13

# ── base ─────────────────────────────────────────────────────────────────
# Shared by builder and prod so the runtime libraries cannot drift between
# what the tests run against and what ships. libmagic1 living only in prod
# is precisely how the first CI run failed: validation.py imports magic at
# module scope, so every test that touches the ingestion path collected with
# "ImportError: failed to find libmagic" in the test image while prod was
# fine.
FROM python:${PYTHON_VERSION}-slim AS base

# python-magic is a binding, not a reimplementation: validation.py reads the
# true content type from the file's bytes rather than trusting an extension
# or a client-supplied MIME, and that needs the C library present.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# ── builder ──────────────────────────────────────────────────────────────
FROM base AS builder

# uv is copied from its own published image rather than pip-installed, so the
# build does not depend on an index being reachable to get the tool that then
# reaches the index.
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

# The venv deliberately lives OUTSIDE /app: docker-compose.yml bind-mounts
# ./backend onto /app for hot reload, and a venv under /app would be shadowed
# by that mount — taking the interpreter on PATH with it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Dependencies resolve from the lockfile in their own layer, so editing source
# does not re-resolve or re-download ~1.7GB of wheels (torch alone is ~530MB).
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
# The backend reads config/frameworks.yaml, which lives at the repo root —
# so the build context is the root and the config is copied explicitly.
COPY config/ /app/config/

# ── models ───────────────────────────────────────────────────────────────
# The embedding model is baked into a layer rather than fetched on first use.
# Startup otherwise makes a network call to huggingface.co before it can
# serve anything, and a transient DNS failure during one has already taken
# this API down — the worker died with no traceback while uvicorn's reloader
# kept holding the port, so the service looked up and answered nothing for
# two hours (CLAUDE.md, "A torn vector index read as an out-of-memory death").
# ~130MB, and it makes both the test run and the container start hermetic.
FROM builder AS models

ENV HF_HOME=/opt/hf
RUN --mount=type=cache,target=/root/.cache/uv \
    /opt/venv/bin/python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# ── test ─────────────────────────────────────────────────────────────────
# CI runs the suite in here. It shares every layer above with prod, so a test
# pass is evidence about the artifact that ships rather than about a
# separately-built environment that merely resembles it.
FROM builder AS test

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY --from=models /opt/hf /opt/hf

# HF_HUB_OFFLINE is safe here precisely because the model is already in the
# layer above: the suite cannot reach the network for a model, so a flaky
# DNS lookup can never become a flaky build.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1

CMD ["pytest", "-q"]

# ── prod ─────────────────────────────────────────────────────────────────
FROM base AS prod

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin meridian

WORKDIR /app

# Only the resolved virtualenv and the application come across. uv, the
# compilers and the dev group stay in the builder.
COPY --from=builder --chown=meridian:meridian /opt/venv /opt/venv
COPY --from=models --chown=meridian:meridian /opt/hf /opt/hf
COPY --chown=meridian:meridian backend/ ./
COPY --chown=meridian:meridian config/ /app/config/

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    CHROMA_PERSIST_DIR=/app/data/chroma

# Writable state lives under /app/data so the root filesystem can be mounted
# read-only where the platform supports it.
RUN mkdir -p /app/data/chroma /app/data/uploads /app/data/reports \
    && chown -R meridian:meridian /app/data

USER meridian

EXPOSE 8000

# Liveness, deliberately: Docker restarts the container on this, and a restart
# does not fix an unreachable Postgres or a spent provider budget. Readiness
# lives at /readyz and is what deployment gating reads.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=4)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
