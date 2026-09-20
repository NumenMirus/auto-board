#!/bin/sh
# Bring up the local development stack via docker compose.
# Detached so the terminal is returned immediately. Use `make logs` to follow.

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

exec docker compose -f infra/docker-compose.yml up -d "$@"