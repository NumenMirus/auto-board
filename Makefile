# AutoBreadboard top-level Makefile. All targets are thin wrappers around the
# scripts under scripts/ so the underlying logic stays shell-portable and
# trivially reproducible in CI without `make`.

SHELL := /bin/sh

# Resolve the repo root from this Makefile so targets work regardless of cwd.
ROOT_DIR := $(shell pwd)

# The Compose project lives under infra/. We anchor on $(ROOT_DIR) so this
# Makefile keeps working from any invocation cwd.
COMPOSE := docker compose -f $(ROOT_DIR)/infra/docker-compose.yml

.DEFAULT_GOAL := help

.PHONY: help dev dev-down test lint typecheck fmt migrate seed logs smoke \
        helm-lint k8s-kind-up k8s-deploy k8s-smoke update-golden build-images

help: ## Show this help.
	@printf 'AutoBreadboard — common targets:\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	    awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- dev stack --------------------------------------------------------------

dev: ## Start the local Docker Compose stack (detached).
	@$(ROOT_DIR)/scripts/dev.sh

dev-down: ## Stop the local Docker Compose stack.
	@$(COMPOSE) down

logs: ## Tail logs from the local Docker Compose stack.
	@$(COMPOSE) logs -f

build-images: ## Build the runtime stage of both application images.
	@$(ROOT_DIR)/scripts/build-images.sh

# --- migrations + seed ------------------------------------------------------

# Both targets resolve to the same Compose "tools" profile service, which runs
# `alembic upgrade head && python -m app.db.seed` against the running stack.
# Seed is idempotent (it only upserts BUILTIN_BOARDS into `board_models`), so
# running `make migrate` after the schema is current is equivalent to `make
# seed`. Both targets are kept as separate phony entries for readability.

migrate: ## Run Alembic migrations + board-model seed (tools profile, on demand).
	@$(COMPOSE) --profile tools run --rm migrate

seed: ## Same as `make migrate` (seed runs inside the migrate command).
	@$(COMPOSE) --profile tools run --rm migrate

# --- tests / lint / typecheck / format ---------------------------------------

test: ## Run backend + frontend test suites.
	@$(ROOT_DIR)/scripts/test.sh

lint: ## Lint backend (ruff check + format --check) and frontend (eslint).
	@cd $(ROOT_DIR)/backend && uv run ruff check app tests
	@cd $(ROOT_DIR)/backend && uv run ruff format --check app tests
	@cd $(ROOT_DIR)/frontend && npx eslint .

typecheck: ## Type-check backend (mypy --strict) and frontend (svelte-check).
	@cd $(ROOT_DIR)/backend && uv run mypy --strict app
	@cd $(ROOT_DIR)/frontend && npx svelte-check --tsconfig ./tsconfig.json

fmt: ## Format backend (ruff) and frontend (prettier).
	@cd $(ROOT_DIR)/backend && uv run ruff format app tests
	@cd $(ROOT_DIR)/frontend && npx prettier --write .

# --- smoke test -------------------------------------------------------------

smoke: ## End-to-end smoke test against a running stack (default localhost:8000).
	@$(ROOT_DIR)/scripts/smoke-test.sh

# --- helm / k8s -------------------------------------------------------------

helm-lint: ## Lint and render the Helm chart (local helm, else Docker fallback).
	@$(ROOT_DIR)/scripts/helm-lint.sh

# `kind` is not installed on every dev machine; print an actionable error and
# fail loudly rather than producing a confusing `command not found`. The k8s
# deployment work belongs to a later wave; the kind cluster config and Helm
# chart may not exist yet, in which case those targets fail harmlessly.

KIND := $(shell command -v kind 2>/dev/null)

k8s-kind-up: ## Create a kind cluster per deploy/local/kind-cluster.yaml (needs `kind`).
	@if [ -z "$(KIND)" ]; then \
	    echo "error: \`kind\` is not installed or not on PATH." >&2; \
	    echo "       Install kind (https://kind.sigs.k8s.io/) or run the" >&2; \
	    echo "       equivalent flow with minikube/k3d/etc." >&2; \
	    exit 1; \
	fi
	@if [ ! -f $(ROOT_DIR)/deploy/local/kind-cluster.yaml ]; then \
	    echo "k8s-kind-up: deploy/local/kind-cluster.yaml not present yet (later wave)" >&2; \
	    exit 1; \
	fi
	@$(KIND) create cluster --config $(ROOT_DIR)/deploy/local/kind-cluster.yaml

k8s-deploy: ## helm upgrade --install the dev values into the autobreadboard namespace.
	@if [ ! -d $(ROOT_DIR)/deploy/helm/autobreadboard ]; then \
	    echo "k8s-deploy: deploy/helm/autobreadboard not present yet (later wave)" >&2; \
	    exit 1; \
	fi
	@if [ ! -f $(ROOT_DIR)/deploy/helm/autobreadboard/values-dev.yaml ]; then \
	    echo "k8s-deploy: values-dev.yaml missing" >&2; exit 1; \
	fi
	@helm upgrade --install autobreadboard $(ROOT_DIR)/deploy/helm/autobreadboard \
	    --namespace autobreadboard --create-namespace \
	    --values $(ROOT_DIR)/deploy/helm/autobreadboard/values-dev.yaml

k8s-smoke: ## Run the smoke test against a port-forwarded k8s service.
	@$(ROOT_DIR)/scripts/smoke-test.sh "http://localhost:8000"

# --- golden test maintenance -----------------------------------------------

# The Renderer task implements golden tests as plain committed `.svg` file
# comparisons (no snapshot plugin in pyproject.toml), so there is no
# `pytest --snapshot-update` workflow to wrap. Regenerating a golden is a
# manual process documented in backend/tests/golden/README.md; this target
# prints the instructions so `make update-golden` is still a useful alias.

update-golden: ## Regenerate golden files (manual — see backend/tests/golden/README.md).
	@echo "Regenerate golden files by re-running the golden test generation script;"
	@echo "see backend/tests/golden/README.md for the manual regen process."
	@echo "(There is no pytest snapshot plugin in pyproject.toml — this is intentional.)"