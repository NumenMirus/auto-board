#!/bin/sh
# Build the runtime stage of both application images for local smoke testing.
# Production builds happen in CI (see .github/workflows/build.yaml) and are
# tagged by git SHA, not by `:local`.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

docker build \
    -f backend/Dockerfile \
    --target runtime \
    -t autobreadboard-api:local \
    backend

docker build \
    -f frontend/Dockerfile \
    --target runtime \
    -t autobreadboard-frontend:local \
    frontend