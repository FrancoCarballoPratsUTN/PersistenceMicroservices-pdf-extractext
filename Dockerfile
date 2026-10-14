# syntax=docker/dockerfile:1
#
# Persistence microservice — production image.
#
# Multi-stage build. The builder resolves dependencies from uv.lock into a
# self-contained virtualenv; the runtime stage ships only that virtualenv and
# the application source, runs as a non-root user and starts uvicorn.
#
# SERVICE_API_TOKEN is required at runtime and has, by design, no default: the
# container refuses to start without it. Provide it at run time, e.g.:
#
#     docker run --rm -p 8000:8000 -e SERVICE_API_TOKEN=<secret> \
#         -e MONGO_URI=mongodb://host.docker.internal:27017 persistence-microservice

# --- Build stage: install dependencies from the lockfile ---------------------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer stays cached until pyproject.toml or uv.lock
# change. --no-dev keeps the runtime image free of pytest/ruff.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Application source last: edits here do not invalidate the dependency layer.
COPY app ./app

# --- Runtime stage -----------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --no-create-home app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

# Docker's default stop signal is already SIGTERM; stating it documents that the
# graceful path below depends on it. Uvicorn stops accepting, drains the
# in-flight requests and only then runs the lifespan shutdown and closes Mongo.
STOPSIGNAL SIGTERM

# /health is open (no token) and does not query MongoDB, so it is a valid
# liveness probe: it stays up while the database is down (SPEC 5.5).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

# --timeout-graceful-shutdown bounds the drain so a stuck request cannot hold the
# process open until Docker's SIGKILL; compose's stop_grace_period sits above it.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20"]
