#!/bin/sh
# Run the full backend + frontend test suites.
# Assumes dev dependencies are installed locally (uv sync for backend,
# npm install for frontend) OR that you intend for the relevant test runner
# to manage them. For local runs, prefer `make test` from the repo root.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR/backend"
uv run pytest tests -q

cd "$ROOT_DIR/frontend"
npx vitest run "$@"