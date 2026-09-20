# syntax=docker/dockerfile:1.7
# AutoBreadboard backend image (Sanic API + arq worker).
# Multi-stage: builder compiles a hermetic `.venv` via `uv sync --frozen`,
# runtime copies only the venv + app sources in as non-root user 10001:10001.
# The dev target adds libcairo2 + fonts-dejavu-core and bind-mounts the source
# tree for hot reload under docker compose.
#
# Image pinning: base is pinned to `python:3.12-slim` (minor tag) by spec.
# TODO(follow-up): pin base images by digest (sha256:...) in CI/production per
# addendum §6.1. Not done in this milestone to avoid locking the local build
# to a digest that isn't refreshed automatically by Renovate yet.

# ----- builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv into the system Python (small, isolated, doesn't pollute .venv).
RUN pip install --no-cache-dir uv

# Copy lock + metadata first so dependency resolution is cached until these change.
COPY pyproject.toml uv.lock ./

# Install runtime dependencies into .venv. Project itself is NOT installed as a
# package (pyproject.toml declares `[tool.uv] package = false`); the runtime
# image runs `python -m app.main` with WORKDIR=/app, so `app/` is importable
# via cwd without installing the project. `--no-install-project` makes the
# intent explicit and skips a noop step.
RUN uv sync --frozen --no-dev --no-install-project

# Now copy the application source and Alembic config. The Python files are not
# installed; they just need to exist on disk for `python -m app.*` to resolve
# them at container start.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# Sync once more with the source present so uv's project fingerprint is fully
# consistent. Idempotent with the previous sync because dependencies haven't
# changed; this is just so the final .venv is "the one built with the source
# tree present", matching how `uv run` behaves locally.
RUN uv sync --frozen --no-dev


# ----- dev (compose target) ---------------------------------------------------
FROM python:3.12-slim AS dev

WORKDIR /app

# cairosvg needs libcairo2; matplotlib/text rendering needs DejaVu Sans.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libcairo2 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# Include dev deps (pytest, mypy, ruff, hypothesis, sanic-testing) under Compose
# so the bind-mounted source can run tests/lints inside the container.
RUN uv sync --frozen

EXPOSE 8000 9100

# Compose overrides command per service (api → python -m app.main,
# worker → python -m app.worker). The default is the API so `docker run`
# without an override gives a usable container.
CMD ["python", "-m", "app.main"]


# ----- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

WORKDIR /app

# Same apt packages as dev: cairosvg needs libcairo2; text needs fonts.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libcairo2 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Unprivileged user. UID/GID 10001 matches the Helm chart and the addendum
# §6.3 securityContext (runAsUser/runAsGroup/fsGroup = 10001).
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid 10001 --create-home app

# Copy the resolved .venv from builder (read-only). This contains every
# runtime dependency pinned in uv.lock — no pip cache, no compiler toolchain.
COPY --from=builder /app/.venv /app/.venv

# Copy the application sources owned by the unprivileged user so the runtime
# process can read (and, where it must, write within /tmp via emptyDir) them.
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app entrypoint-api.sh entrypoint-worker.sh ./
RUN chmod +x entrypoint-api.sh entrypoint-worker.sh

USER 10001:10001

EXPOSE 8000 9100

# Default command runs the API; the worker is launched by the same image with
# a different `command:` override in the Helm Deployment / Compose service.
CMD ["python", "-m", "app.main"]