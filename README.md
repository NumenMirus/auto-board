# AutoBreadboard

> **Safety notice** — La breadboard è destinata a prototipi a bassa tensione e
> bassa energia. Verificare limiti di corrente, polarità, tensioni e sicurezza
> prima di alimentare il circuito. AutoBreadboard non garantisce che un
> circuito sia "sicuro" solo perché la netlist è connessa correttamente.

AutoBreadboard is a web application that turns a through-hole netlist (JSON) into
a verified breadboard layout. It models a real half-size 400-tie-point
breadboard, auto-places components, routes jumpers, verifies the result
topologically (DSU), lets the user edit manually with live verification, and
exports an assembly guide (SVG / PNG / PDF / JSON / BOM CSV / jumper CSV).

The full requirements live in the two spec documents at the repo root:

- [`specifica-agente-autobreadboard.md`](./specifica-agente-autobreadboard.md) —
  product specification (scope, data model, solver, UI, exports).
- [`addendum-kubernetes-autobreadboard.md`](./addendum-kubernetes-autobreadboard.md) —
  Kubernetes-ready addendum that pins the stack (Python Sanic + arq/Redis +
  PostgreSQL + S3/MinIO, SvelteKit SPA on Nginx) and the deployment shape
  (Compose for dev, Helm + kind for prod).

## Project layout

```
auto-breadboard/
├── backend/          # Python Sanic API + arq worker + pure-Python solver core
│   ├── app/
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/         # SvelteKit SPA (adapter-static)
│   ├── src/
│   ├── static/
│   ├── Dockerfile
│   └── nginx.conf
├── deploy/           # Helm chart + kind/local manifests
│   ├── helm/autobreadboard/
│   └── local/
├── infra/            # docker-compose.yml for local dev (postgres/redis/minio)
├── scripts/          # dev.sh, test.sh, build-images.sh, helm-lint.sh, smoke-test.sh
├── .github/workflows/  # ci.yaml, build.yaml, deploy.yaml
├── Makefile
└── README.md
```

## Prerequisites

- Docker (with Compose v2 / `docker compose` available)
- `uv` (Python package manager) — https://docs.astral.sh/uv/
- Node.js 22+ and npm (for local frontend lint/typecheck/test work outside Docker)
- `kind` and `helm` **only if** you intend to run the Kubernetes smoke path;
  both are not required for the Docker Compose quickstart. CI runs them in
  containers if missing locally.

## Quickstart (Docker Compose)

```sh
# 1. Bring up the stack (postgres + redis + minio + api + worker + frontend).
make dev

# 2. Apply migrations and seed the board-model registry.
make migrate      # or `make seed` — they are the same command today

# 3. Open the UI.
#    Frontend:    http://localhost:8080
#    API:         http://localhost:8000
#    MinIO console: http://localhost:9001   (minioadmin / minioadmin)
```

Useful follow-ups:

```sh
make logs         # tail every service
make test         # backend pytest + frontend vitest
make lint         # ruff check + ruff format --check + eslint
make typecheck    # mypy --strict + svelte-check
make smoke        # /healthz, /readyz, /version smoke test
make dev-down     # stop the stack
```

### Configuration

Settings arrive from environment variables whose names match the fields of
`backend/app/settings.py` uppercased (`DATABASE_URL`, `REDIS_URL`,
`S3_BUCKET`, ...). In `development`, the API also reads `.env` from the repo
root; in `staging`/`production` config arrives exclusively from Kubernetes
ConfigMap/Secret-injected env vars. A safe dev template lives at
[`.env.example`](./.env.example) — copy it to `.env` and edit.

`CORS_ORIGINS` and `TRUSTED_HOSTS` are `list[str]` fields; `pydantic-settings`
parses them from JSON arrays, so the value must be quoted JSON in the env:

```sh
CORS_ORIGINS='["http://localhost:8080"]'
```

### Building the application images

```sh
make build-images    # autobreadboard-api:local + autobreadboard-frontend:local
```

CI (`.github/workflows/build.yaml`) builds and pushes images tagged by git SHA.

## Kubernetes path

```sh
# Cluster (kind — must be installed)
make k8s-kind-up
make k8s-deploy       # helm upgrade --install against values-dev.yaml
kubectl rollout status deployment/autobreadboard-api -n autobreadboard
kubectl port-forward svc/autobreadboard-frontend 8080:8080 -n autobreadboard
make k8s-smoke
```

Lint the chart at any time:

```sh
make helm-lint       # uses local helm if present, else alpine/helm:3.19.0
```

## Development notes

- The backend runs via `python -m app.main` (API) and `python -m app.worker`
  (arq worker); both share the same Docker image and pick their role from
  `command:` in Compose or the Helm Deployment.
- The frontend uses `adapter-static` with `fallback: 'index.html'`; the SPA
  bundle is served by `nginx-unprivileged` on port 8080. The API base URL is
  injected at runtime via `window.__AUTOBREADBOARD_CONFIG__` defined in
  `runtime-config.js` (mounted by the ConfigMap in k8s).
- `cairosvg` (PNG/PDF export) requires the system library `libcairo2` and the
  DejaVu Sans font package at runtime; both are installed in the Docker image.
- Determinism: the solver uses only `random.Random(seed)` instances passed
  explicitly. No module-level randomness, no set/dict iteration order
  dependence for anything that affects output.

## License

Private — see internal documentation.