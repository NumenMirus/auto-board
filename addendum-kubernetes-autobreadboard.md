# Addendum — AutoBreadboard Kubernetes-ready (Sanic + Svelte)

Questo documento integra la specifica principale di AutoBreadboard. Rende il progetto pronto per Kubernetes sin dalla prima milestone, senza introdurre complessità operativa non necessaria nel flusso di sviluppo locale.

Obiettivo: l'applicazione deve poter essere avviata in Docker Compose per lo sviluppo e distribuita su Kubernetes tramite Helm, con configurazione esterna, health check, migrazioni, osservabilità e gestione dei job solver separabile dal web server.

---

## 1. Principi di deployment

Applicare le seguenti regole architetturali.

1. Ogni processo è stateless: nessun dato di progetto, job o file esportato deve dipendere dal filesystem locale del container.
2. La configurazione arriva da environment variables, Secret, ConfigMap o file montati.
3. L'immagine applicativa è immutabile, non contiene segreti, non richiede scrittura nella root filesystem ed esegue come utente non-root.
4. Backend API e solver worker sono processi distinti anche se inizialmente usano la stessa immagine Docker.
5. Lo stato persistente vive in PostgreSQL; Redis è usato per cache, lock, coda e stato effimero dei job.
6. I file esportati vengono salvati in object storage compatibile S3, non in disco locale. Per sviluppo usare MinIO.
7. Le migrazioni database sono eseguite da un Job Kubernetes o init container controllato, non automaticamente da ogni replica API.
8. I job di ottimizzazione devono poter essere interrotti e rieseguiti senza corrompere il progetto.
9. La UI deve essere servita da un container separato, preferibilmente Nginx unprivileged, con configurazione runtime dell'URL API.
10. Ogni servizio deve avere request/CPU/memory limits e probe Kubernetes.

---

## 2. Topologia iniziale

```text
                       ┌─────────────────────┐
                       │ Ingress / Gateway   │
                       │ TLS termination     │
                       └─────────┬───────────┘
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
       ┌────────▼─────────┐             ┌─────────▼────────┐
       │ frontend Service │             │ api Service       │
       │ Svelte + Nginx   │             │ Sanic API         │
       └────────┬─────────┘             └───────┬───────────┘
                │                               │
                │                         ┌─────▼─────┐
                │                         │ PostgreSQL│
                │                         └───────────┘
                │                               │
                │                         ┌─────▼─────┐
                │                         │ Redis     │
                │                         └─────┬─────┘
                │                               │
                │                        ┌──────▼──────┐
                │                        │ Solver worker│
                │                        │ Python       │
                │                        └──────┬──────┘
                │                               │
                │                         ┌─────▼─────┐
                └────────────────────────►│ S3 / MinIO│
                                          └───────────┘
```

Il frontend non deve chiamare PostgreSQL, Redis o object storage. Il browser parla solo con API/gateway.

---

## 3. Repository layout

Strutturare il repository così:

```text
autobreadboard/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── db/
│   │   ├── jobs/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── settings.py
│   │   ├── worker.py
│   │   └── main.py
│   ├── alembic/
│   ├── tests/
│   ├── Dockerfile
│   ├── entrypoint-api.sh
│   ├── entrypoint-worker.sh
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   ├── static/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── package.json
├── deploy/
│   ├── helm/
│   │   └── autobreadboard/
│   │       ├── Chart.yaml
│   │       ├── values.yaml
│   │       ├── values-dev.yaml
│   │       ├── values-staging.yaml
│   │       ├── values-production.yaml
│   │       └── templates/
│   │           ├── _helpers.tpl
│   │           ├── api-deployment.yaml
│   │           ├── api-service.yaml
│   │           ├── frontend-deployment.yaml
│   │           ├── frontend-service.yaml
│   │           ├── worker-deployment.yaml
│   │           ├── migration-job.yaml
│   │           ├── ingress.yaml
│   │           ├── configmap.yaml
│   │           ├── secret.yaml
│   │           ├── serviceaccount.yaml
│   │           ├── networkpolicy.yaml
│   │           ├── pdb.yaml
│   │           └── hpa.yaml
│   ├── kustomize/                 # opzionale, non duplicare Helm
│   └── local/
│       ├── kind-cluster.yaml
│       └── ingress-values.yaml
├── infra/
│   ├── docker-compose.yml
│   ├── postgres/
│   ├── minio/
│   └── redis/
├── scripts/
│   ├── dev.sh
│   ├── test.sh
│   ├── build-images.sh
│   ├── helm-lint.sh
│   └── smoke-test.sh
├── .github/workflows/
│   ├── ci.yaml
│   ├── build.yaml
│   └── deploy.yaml
├── Makefile
└── README.md
```

Helm è la sorgente primaria delle manifest Kubernetes. Non mantenere una seconda copia divergente di manifest raw.

---

## 4. Backend Sanic

### 4.1 Ruoli del backend

Usare la stessa immagine `backend` con due comandi diversi:

```text
API process:
python -m app.main

Worker process:
python -m app.worker
```

L'API Sanic deve:

- autenticare/autorizzare in futuro;
- validare input con Pydantic;
- salvare progetto e layout in PostgreSQL;
- inviare lavori solver nella queue Redis;
- esporre stato job e risultati;
- produrre URL firmati o proxy per export object storage;
- restare rapido e non fare simulated annealing lungo nella request HTTP.

Il worker deve:

- prelevare job dalla queue;
- acquisire lock per progetto/job;
- eseguire placement, routing, validazione e export;
- pubblicare progress e stato in Redis/PostgreSQL;
- salvare layout risultante e artefatti;
- rispettare cancellation/timeouts;
- poter essere terminato senza lasciare job bloccati permanentemente.

### 4.2 Coda job

Usare inizialmente Redis con un worker dedicato. Selezionare una libreria o implementazione stabile compatibile con async Python; valutare `arq` per code asyncio oppure RQ/Celery se il progetto richiede ecosistema più vasto.

Contratto minimo job:

```python
class SolverJobPayload(BaseModel):
    job_id: UUID
    project_id: UUID
    revision_id: UUID
    operation: Literal["place", "route", "solve", "validate", "export"]
    seed: int
    options: SolveOptions
    requested_by: UUID | None = None
```

Requisiti:

- idempotency key per evitare doppie esecuzioni;
- lock per `project_id + revision_id + operation`;
- timeout massimo configurabile;
- retry solo per errori transitori;
- errori solver deterministici non vanno ritentati automaticamente;
- persistere error message, traceback sanitizzato, timing e solver trace;
- progress con percentuale e fase (`validate`, `place`, `route`, `verify`, `export`).

### 4.3 Settings

Usare `pydantic-settings` e un modello unico.

```python
class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: PostgresDsn
    redis_url: RedisDsn

    s3_endpoint_url: AnyHttpUrl | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: list[str] = []
    trusted_hosts: list[str] = []

    solver_default_timeout_seconds: int = 60
    solver_max_timeout_seconds: int = 600
    worker_concurrency: int = 1

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )
```

In produzione non montare `.env`; usare Secret e ConfigMap.

### 4.4 API operational endpoints

Implementare endpoint distinti:

```text
GET /healthz  → processo HTTP vivo; senza dipendenze esterne
GET /readyz   → pronto a ricevere traffico: DB e Redis raggiungibili
GET /metrics  → metriche Prometheus, se autorizzato/rete interna
GET /version  → build SHA, image version, schema/API version
```

Semantica:

- `healthz`: non fare query DB/Redis; serve per liveness probe.
- `readyz`: controllare dipendenze essenziali con timeout stretto; serve per readiness probe.
- `metrics`: non esporre dettagli o segreti.

---

## 5. Database e persistenza

### 5.1 PostgreSQL

Usare PostgreSQL anche in sviluppo Compose, non SQLite, per evitare differenze di locking, tipi JSON e migrazioni.

Entità minime:

```text
projects
project_revisions
layouts
solver_jobs
solver_job_events
exports
board_models
footprint_overrides
```

Regole:

- schema migrations con Alembic;
- JSONB per netlist, opzioni solver, layout e diagnostica se conveniente;
- revisioni immutabili per input solver;
- ogni job punta a una revisione specifica, non all'ultima bozza mutabile;
- ottimistic locking/versione per editing concorrente;
- indici su `project_id`, `revision_id`, `status`, `created_at`;
- policy di retention per solver trace ed export temporanei.

### 5.2 Object storage

Salvare artefatti grandi o derivati in S3:

- SVG/PNG/PDF export;
- CSV BOM e jumper list;
- upload di `.kicad_sch` originali;
- eventuali solver trace grandi;
- snapshot scaricabili.

Il DB conserva metadata, content type, checksum, storage key e retention date.

In sviluppo usare MinIO. In produzione usare MinIO gestito o un provider S3 compatibile.

Non usare `emptyDir`, PVC del pod API o filesystem del worker come storage di progetto definitivo.

---

## 6. Container images

### 6.1 Backend Dockerfile

Creare immagine multi-stage, minimale e riproducibile:

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "app.main"]
```

Adattare il lockfile/tool reale scelto (`uv`, Poetry o pip-tools), ma mantenere lock deterministico.

Requisiti:

- pin delle image base tramite digest in CI/produzione;
- no `latest`;
- utente non-root;
- filesystem root read-only in Kubernetes;
- nessun secret copiato in image;
- SBOM e image scan in CI;
- tag immagine: git SHA immutabile, semver/release opzionale.

### 6.2 Frontend Dockerfile

Build Svelte separato da runtime Nginx unprivileged:

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/build /usr/share/nginx/html
EXPOSE 8080
```

Non incorporare URL/secret di ambiente di produzione nel bundle se devono variare fra cluster. Esporre configurazione runtime con un file `runtime-config.js` generato da ConfigMap o entrypoint.

### 6.3 Security context

Tutti i pod applicativi devono avere:

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  fsGroup: 10001
  seccompProfile:
    type: RuntimeDefault

containers:
  - name: app
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
```

Montare `emptyDir` soltanto per `/tmp` quando strettamente necessario, con `sizeLimit`.

---

## 7. Helm chart

### 7.1 Risorse minime

Il chart deve generare:

- `Deployment` API;
- `Service` API ClusterIP;
- `Deployment` frontend;
- `Service` frontend ClusterIP;
- `Deployment` worker;
- `Job` migration opzionale/Helm hook;
- `Ingress` opzionale;
- `ConfigMap` applicativa;
- riferimenti a Secret già esistenti oppure Secret opzionale per dev;
- `ServiceAccount` senza privilegi Kubernetes non necessari;
- `NetworkPolicy` opzionale ma abilitata in staging/production;
- `PodDisruptionBudget`;
- `HorizontalPodAutoscaler` opzionale;
- `PodMonitor`/`ServiceMonitor` opzionale;
- migration hook con policy di cleanup.

PostgreSQL, Redis e MinIO non devono essere embedded di default nel chart di produzione. Supportare endpoint esterni e, al massimo, dependency opzionali per sviluppo/demo.

### 7.2 Values essenziali

```yaml
global:
  environment: production
  imagePullSecrets: []

api:
  image:
    repository: ghcr.io/example/autobreadboard-api
    tag: "sha-REPLACE"
    pullPolicy: IfNotPresent
  replicaCount: 2
  service:
    port: 8000
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: "1"
      memory: 768Mi
  autoscaling:
    enabled: false
    minReplicas: 2
    maxReplicas: 8
    targetCPUUtilizationPercentage: 70

worker:
  image:
    repository: ghcr.io/example/autobreadboard-api
    tag: "sha-REPLACE"
  replicaCount: 1
  concurrency: 1
  resources:
    requests:
      cpu: 250m
      memory: 512Mi
    limits:
      cpu: "2"
      memory: 2Gi

frontend:
  image:
    repository: ghcr.io/example/autobreadboard-frontend
    tag: "sha-REPLACE"
  replicaCount: 2
  service:
    port: 8080
  resources:
    requests:
      cpu: 25m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 128Mi

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: autobreadboard.example.com
      paths:
        - path: /
          pathType: Prefix
          service: frontend
        - path: /api
          pathType: Prefix
          service: api
  tls: []

config:
  environment: production
  logLevel: INFO
  corsOrigins:
    - https://autobreadboard.example.com
  solverDefaultTimeoutSeconds: 60
  solverMaxTimeoutSeconds: 600

secrets:
  existingSecret: autobreadboard-runtime

postgres:
  host: postgres.example.internal
  port: 5432
  database: autobreadboard
  sslMode: require

redis:
  url: redis://redis.example.internal:6379/0

s3:
  endpointUrl: https://s3.example.internal
  bucket: autobreadboard
  region: us-east-1

networkPolicy:
  enabled: true

migration:
  enabled: true
  hook: pre-install,pre-upgrade
```

Mai mettere valori segreti in `values.yaml` versionato. Usare `existingSecret`, External Secrets, SOPS/age, Sealed Secrets o il secret manager scelto dall'infrastruttura.

### 7.3 Probes

API:

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: http
  failureThreshold: 30
  periodSeconds: 2

livenessProbe:
  httpGet:
    path: /healthz
    port: http
  initialDelaySeconds: 5
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /readyz
    port: http
  initialDelaySeconds: 3
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 3
```

Worker:

- readiness: processo connesso a Redis e pronto a prelevare job;
- liveness: heartbeat locale/Redis o endpoint locale, senza dipendere da un job attivo;
- prevedere `terminationGracePeriodSeconds` sufficiente per terminare in modo controllato o rimettere il job in coda.

Frontend:

```yaml
livenessProbe:
  httpGet:
    path: /
    port: http
readinessProbe:
  httpGet:
    path: /
    port: http
```

### 7.4 Graceful shutdown

API Sanic:

- intercettare SIGTERM;
- smettere di accettare nuove richieste;
- concludere richieste in corso entro timeout;
- chiudere DB/Redis pool;
- restituire non-ready prima di terminare.

Worker:

- smettere di prelevare nuovi job;
- persistere checkpoint/progress quando possibile;
- marcare job come retryable/requeued se interrotto;
- rispettare `terminationGracePeriodSeconds`;
- non lasciare lock Redis senza TTL.

---

## 8. Networking e sicurezza

### 8.1 Ingress

Usare un Ingress controller o Gateway API gestito dal cluster. Terminare TLS con cert-manager o infrastruttura equivalente.

Routing consigliato:

```text
/      → frontend service
/api   → API service
```

Configurare:

- HTTPS obbligatorio in staging/production;
- redirect HTTP → HTTPS;
- limite dimensione upload;
- timeout upload/solver status ragionevoli;
- compressione statici dove supportata;
- rate limit e WAF a livello gateway se richiesto.

### 8.2 CORS e CSRF

Se frontend e API condividono stesso hostname con path `/api`, minimizzare CORS. Se usano host distinti:

- lista esplicita di origin ammessi;
- mai `*` con credenziali;
- cookie `Secure`, `HttpOnly`, `SameSite` appropriato;
- protezione CSRF se usa cookie session.

### 8.3 NetworkPolicy

In production, configurare policy deny-by-default e permettere soltanto:

- Ingress controller → frontend/API;
- frontend → API se necessario internamente;
- API → PostgreSQL, Redis, S3;
- worker → PostgreSQL, Redis, S3;
- DNS verso kube-dns;
- Prometheus → `/metrics` se abilitato.

Non assegnare RBAC Kubernetes al backend se non serve. ServiceAccount deve avere automount token disabilitato salvo necessità dimostrata.

```yaml
automountServiceAccountToken: false
```

### 8.4 Secret management

Supportare fin dall'inizio:

- `existingSecret` Kubernetes;
- rotazione delle credenziali senza rebuild delle image;
- secret separati per DB, Redis, S3 e auth futura;
- nessun logging di `DATABASE_URL`, token S3, cookie secret o PII.

In ambienti seri preferire External Secrets Operator + Vault/1Password/Cloud Secret Manager, oppure SOPS con age per GitOps.

---

## 9. Osservabilità

### 9.1 Logging

Backend e worker devono emettere JSON log su stdout.

Campi minimi:

```text
timestamp
level
service
environment
request_id
trace_id
project_id (se applicabile)
job_id (se applicabile)
revision_id (se applicabile)
operation
message
duration_ms
error_code
```

Non loggare netlist completa, contenuto upload o segreti a livello INFO. Abilitare dettagli tecnici soltanto in debug controllato.

### 9.2 Metrics

Esporre metriche Prometheus:

```text
http_requests_total
http_request_duration_seconds
http_requests_in_progress
solver_jobs_total{operation,status}
solver_job_duration_seconds{operation}
solver_queue_depth
solver_active_jobs
solver_unrouted_nets
solver_diagnostics_total{severity,code}
export_jobs_total{format,status}
database_pool_connections
redis_errors_total
```

Misurare p50/p95/p99 del solver per fixture/circuit size. Non usare metriche con label ad alta cardinalità come `project_id`.

### 9.3 Tracing

Preparare OpenTelemetry per API e worker:

- propagare `traceparent` dalla request al job;
- tracciare DB, Redis, S3 e fasi solver;
- rendere exporter configurabile;
- non rendere tracing obbligatorio per l'avvio locale.

---

## 10. CI/CD

### 10.1 Pipeline CI pull request

Ogni pull request deve eseguire:

```text
Backend:
- ruff check
- ruff format --check
- mypy/pyright
- pytest unit + integration
- Hypothesis/property tests rilevanti

Frontend:
- npm ci
- lint
- typecheck
- vitest
- build

Deploy:
- docker build backend/frontend
- image scan
- helm lint
- helm template con values dev/staging/production
- kubeconform/kubeval sui manifest renderizzati
- test smoke opzionale su kind
```

### 10.2 Build release

Su merge/tag:

1. build immagini multi-arch se richiesto;
2. tag con git SHA immutabile;
3. genera SBOM;
4. firma immagini se infrastruttura lo supporta;
5. push registry;
6. aggiorna manifest GitOps o esegui deploy Helm controllato;
7. esegui migration job;
8. attende rollout;
9. smoke test `/healthz`, `/readyz`, UI e una fixture solver;
10. rollback automatico o manuale se readiness/smoke test falliscono.

### 10.3 Migrazioni e rollback

Le migration devono essere backward-compatible quando possibile:

```text
Expand → deploy application compatibile → migrate data → contract in release successiva
```

Non fare downgrade automatici di schema durante rollback applicativo. Validare la compatibilità di ogni migration in CI contro una snapshot DB di test.

---

## 11. Docker Compose locale

Fornire `infra/docker-compose.yml` con:

```text
frontend
api
worker
postgres
redis
minio
minio-init
```

Requisiti:

- bind mount del codice solo in dev;
- hot reload backend/frontend;
- PostgreSQL/Redis/MinIO con healthcheck;
- bucket MinIO creato da un init container/script idempotente;
- valori locali in `.env.example`, mai `.env` committato;
- comandi Makefile semplici.

Esempi:

```makefile
make dev             # avvia compose
make dev-down        # ferma stack
make test            # backend + frontend test
make lint            # lint backend + frontend
make migrate         # alembic upgrade head nel container api
make seed            # carica board models e footprint base
make logs            # tail servizi
make k8s-kind-up     # crea cluster kind e deploy Helm dev
make k8s-deploy      # helm upgrade --install
make k8s-smoke       # controlli health e fixture
```

Il runtime locale deve replicare le dipendenze di produzione: PostgreSQL, Redis e S3 compatibile.

---

## 12. Kubernetes locale

Supportare `kind` come percorso predefinito per sviluppatori che usano Kubernetes localmente.

Flusso:

```text
kind create cluster --config deploy/local/kind-cluster.yaml
helm upgrade --install autobreadboard deploy/helm/autobreadboard \
  --namespace autobreadboard --create-namespace \
  --values deploy/helm/autobreadboard/values-dev.yaml
kubectl rollout status deployment/autobreadboard-api -n autobreadboard
kubectl port-forward service/autobreadboard-frontend 8080:8080 -n autobreadboard
```

Per dev su cluster locale:

- usare image locali caricate con `kind load docker-image`;
- disabilitare image pull remoto o usare registry locale;
- usare Postgres/Redis/MinIO di sviluppo nel namespace oppure Compose esterno esplicitamente documentato;
- non richiedere cloud resources per il primo deploy locale.

---

## 13. Autoscaling e capacità

### API

L'API è stateless e può scalare orizzontalmente. Usare HPA solo dopo avere metriche reali.

Condizioni iniziali suggerite:

```text
minReplicas: 2 in production
CPU request: 100m
Memory request: 256Mi
HPA target CPU: 70%
```

### Worker

Non scalare worker solo su CPU se i job sono CPU-bound e lunghi. Iniziare con un numero controllato di worker e concorrenza 1 per pod. Poi introdurre metriche di queue depth, KEDA o autoscaling custom.

Parametri iniziali:

```text
worker replicas: 1
worker concurrency: 1
CPU request: 250m
CPU limit: 2
Memory request: 512Mi
Memory limit: 2Gi
```

Ogni job solver deve avere un budget CPU/memoria/tempo. Un input avverso o una netlist complessa non deve poter esaurire il nodo.

### Pod disruption budget

Per API e frontend in produzione:

```yaml
minAvailable: 1
```

Per worker, evitare PDB troppo restrittivo se esiste un solo replica; i job devono essere recoverable.

---

## 14. Configurazione runtime frontend

Il bundle Svelte viene costruito una volta e distribuito in ambienti diversi. L'URL API deve poter cambiare senza rebuild.

Implementare un file runtime servito da Nginx, ad esempio:

```js
window.__AUTOBREADBOARD_CONFIG__ = {
  apiBaseUrl: "/api/v1",
  environment: "production",
  buildSha: "unknown"
};
```

Montare `runtime-config.js` da ConfigMap oppure generarlo al container startup in una directory writable dedicata. Il frontend legge il valore all'avvio.

Non inserire secret nel runtime config: è pubblico per definizione.

---

## 15. Job e consistenza

### 15.1 Revisioni immutabili

Quando l'utente clicca `Solve`:

1. salvare una nuova `project_revision` immutabile;
2. creare un `solver_job` collegato alla revisione;
3. accodare job;
4. il worker legge esclusivamente quella revisione;
5. salva un layout/output come risultato della revisione;
6. il frontend può scegliere se applicare il risultato alla bozza corrente.

Questo evita che un worker finisca su una netlist modificata dall'utente nel frattempo.

### 15.2 Cancellation

L'utente può richiedere annullamento. Il worker deve controllare periodicamente un cancellation flag, in particolare tra iterazioni di simulated annealing, route retry e export.

Non è obbligatorio interrompere un singolo calcolo CPU puro nel microsecondo; è obbligatorio che la cancellazione sia osservata entro un intervallo ragionevole e che lo stato finale sia coerente.

### 15.3 Idempotenza

Usare chiave di idempotenza per endpoint che avviano job. Un retry HTTP non deve creare due solve identici involontari.

---

## 16. Definition of done K8s-ready

Un milestone è Kubernetes-ready solo se soddisfa tutti questi requisiti:

- immagini backend e frontend buildabili senza dipendere da file locali non versionati;
- immagini eseguibili come utente non-root;
- API ha `/healthz`, `/readyz`, `/version`;
- worker ha lifecycle graceful e job recoverable;
- configurazione esclusivamente tramite environment/ConfigMap/Secret;
- nessun segreto in repository, image o log;
- migrazioni Alembic eseguite da Job controllato;
- PostgreSQL, Redis e S3 esterni/configurabili;
- Helm chart passa `helm lint` e rendering valido con tutti i values environment;
- deployment ha resource requests/limits, probes e securityContext;
- deployment locale Compose funziona;
- deployment kind/Helm funziona;
- CI esegue lint, test, build, Helm render e validazione manifest;
- smoke test crea un progetto fixture, accoda un solver job, verifica risultato ed export;
- rollback applicativo non richiede perdita di dati.

---

## 17. Prompt operativo Kubernetes per l'agente

> Implementa AutoBreadboard come sistema Kubernetes-ready fin dalla prima milestone. Lo stack è Sanic + Svelte: il backend Python ospita API, domain core e worker solver; il frontend Svelte è una SPA servita separatamente. Mantieni API e worker come processi distinti che usano la stessa image backend. Il solver deve restare puro e indipendente da Sanic, Redis e database; API e worker lo orchestrano.
>
> Usa PostgreSQL per persistenza, Redis per queue/lock/stato effimero e S3-compatible object storage per export e upload. Non salvare stato definitivo nel filesystem dei pod. Usa Docker Compose con PostgreSQL, Redis e MinIO in sviluppo. Usa Helm come sorgente primaria delle risorse Kubernetes, con valori dev/staging/production e supporto kind locale.
>
> Ogni container deve essere non-root, immutable, senza segreti incorporati, con filesystem root read-only dove possibile, resource requests/limits, probe e graceful shutdown. Implementa `/healthz`, `/readyz`, `/version` e metriche. Esegui Alembic da Job Kubernetes controllato, non al boot di ogni API pod. Non incorporare PostgreSQL/Redis/MinIO nel chart di produzione per default; configurarli come servizi esterni tramite ConfigMap/Secret.
>
> Tratta le solve operation come job asincroni revisionati e idempotenti. Salva input su revisioni immutabili, supporta cancellation e retry controllato, e non perdere job al restart del pod. Mantieni CI con test backend/frontend, image build e scan, Helm lint/template, validazione manifest e smoke test su kind. Non dichiarare una milestone completata se non si avvia sia in Compose sia tramite Helm su kind.
