/**
 * Typed fetch wrapper for the AutoBreadboard API.
 *
 * Conventions:
 *   - Every request gets a fresh `X-Request-Id` (UUID v4). The Sanic
 *     middleware echoes it in logs and the response header.
 *   - All non-2xx responses throw `ApiError`. The backend always serialises
 *     failures as `{"error":{"code":..., "message":..., "details":...}}`
 *     (see `app/core/errors.py::to_response`). Bodies that don't match that
 *     shape become `ApiError{code:"UNKNOWN"}` rather than throwing a parse
 *     error to the caller.
 *   - `path` is joined onto the runtime-configured `apiBaseUrl` with a
 *     single forward-slash; callers pass paths starting with `/` or not,
 *     either works.
 */

import { getRuntimeConfig } from '../config';

export class ApiError extends Error {
  code: string;
  details: Record<string, unknown> | undefined;
  status: number;

  constructor(
    code: string,
    message: string,
    status: number,
    details: Record<string, unknown> | undefined = undefined
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function joinUrl(base: string, path: string): string {
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path;
  }
  const trimmedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  const trimmedPath = path.startsWith('/') ? path : `/${path}`;
  return `${trimmedBase}${trimmedPath}`;
}

function generateRequestId(): string {
  // crypto.randomUUID is available in all modern browsers and Node 19+.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  // Fallback: timestamp + random hex. Rarely exercised; keeps the test
  // environment (which polyfills crypto.randomUUID) happy too.
  return `req-${Date.now().toString(16)}-${Math.random().toString(16).slice(2, 10)}`;
}

interface ErrorEnvelope {
  error?: {
    code?: unknown;
    message?: unknown;
    details?: unknown;
  };
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return (
    typeof value === 'object' &&
    value !== null &&
    'error' in value &&
    typeof (value as { error: unknown }).error === 'object' &&
    (value as { error: unknown }).error !== null
  );
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const base = getRuntimeConfig().apiBaseUrl;
  const url = joinUrl(base, path);

  const headers = new Headers(init.headers ?? undefined);
  headers.set('X-Request-Id', generateRequestId());
  if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  const response = await fetch(url, { ...init, headers });

  if (!response.ok) {
    // Try to parse the standard error envelope. If the body isn't JSON or
    // doesn't match, fall back to a generic UNKNOWN error.
    let code = 'UNKNOWN';
    let message = `Request failed with status ${response.status}`;
    let details: Record<string, unknown> | undefined;

    try {
      const parsed: unknown = await response.json();
      if (isErrorEnvelope(parsed) && parsed.error) {
        if (typeof parsed.error.code === 'string') {
          code = parsed.error.code;
        }
        if (typeof parsed.error.message === 'string') {
          message = parsed.error.message;
        }
        if (parsed.error.details && typeof parsed.error.details === 'object') {
          details = parsed.error.details as Record<string, unknown>;
        }
      }
    } catch {
      // Body wasn't JSON; keep the UNKNOWN code.
    }

    throw new ApiError(code, message, response.status, details);
  }

  // 204 No Content — return undefined and let the caller pick a type.
  if (response.status === 204) {
    return undefined as T;
  }

  // Some success responses are intentionally empty (rare). Treat empty
  // bodies as `undefined` rather than throwing a JSON parse error.
  const text = await response.text();
  if (text.length === 0) {
    return undefined as T;
  }

  return JSON.parse(text) as T;
}

// ---------------------------------------------------------------------------
// Typed API surface — high-level wrappers around `apiFetch` for every route
// in the AutoBreadboard HTTP API. Kept in this file (rather than split into
// `projects.ts`, `jobs.ts`, …) because they're thin and they share the same
// error-envelope semantics. The function set is the contract described in
// `local://autobreadboard-service-plan.md` step 2C. All field names match
// the camelCase wire shape declared in `frontend/src/lib/types.ts`; Pydantic
// aliases the same names on the backend.
//
// Every exported function is async, returns the parsed body (or undefined
// for 204 endpoints), and surfaces non-2xx responses as `ApiError`. They
// never mutate global state — selection, undo history, etc. live in
// `project.svelte.ts`.
// ---------------------------------------------------------------------------

import type {
  AnyBoardModel,
  BoardKind,
  BreadboardFootprint,
  Layout,
  Net,
  ProjectDocument,
  ProjectListResponse,
  Component,
  Diagnostic,
  LayoutScore,
  SolverTrace,
  TraceLayout
} from '../types';

// ---- Wire shapes that aren't already in `types.ts` -------------------------

export interface ProjectEnvelope {
  id: string;
  name: string;
  boardModelId: string;
  draftVersion: number;
  document: ProjectDocument;
  createdAt: string;
  updatedAt: string;
}

export interface ProjectCreateRequest {
  name: string;
  boardModelId: string;
  document?: ProjectDocument;
}

export interface RevisionEnvelope {
  id: string;
  projectId: string;
  revisionNumber: number;
  document: ProjectDocument;
  documentSha256: string;
  createdAt: string;
}

export type SolverOperation =
  | 'place'
  | 'route'
  | 'solve'
  | 'optimize'
  | 'validate'
  | 'export'
  | 'trace-route'
  | 'trace-solve';

export interface SolverOptions {
  seed?: number;
  preset?: 'fast' | 'balanced' | 'quality';
  placementWeights?: Record<string, number>;
  routingWeights?: Record<string, number>;
  allowCriticalNetClasses?: boolean;
  timeoutSeconds?: number;
  maxPlacementRestarts?: number;
  maxLocalSearchIterations?: number;
  maxRipupIterations?: number;
}

export interface JobCreateRequest {
  operation: SolverOperation;
  seed?: number;
  options?: SolverOptions;
  revisionId?: string;
}

export type JobStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled';

export interface JobEnvelope {
  id: string;
  projectId: string;
  revisionId: string | null;
  operation: SolverOperation;
  status: JobStatus;
  progressPercent: number;
  progressPhase: string | null;
  errorCode?: string | null;
  errorMessage?: string | null;
  resultLayoutId?: string | null;
  traceparent?: string | null;
  createdAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface JobEvent {
  id: number;
  at: string;
  phase: string;
  percent: number;
  level: string;
  code: string | null;
  message: string;
}

export interface JobResultEnvelope {
  layout: Layout | TraceLayout;
  score: LayoutScore;
  diagnostics: Diagnostic[];
  trace?: SolverTrace | null;
}

export interface LayoutEnvelope {
  id: string;
  projectId: string;
  layout: Layout | TraceLayout;
  score: LayoutScore | null;
  diagnostics: Diagnostic[] | null;
  source: 'manual' | 'solver';
  createdAt: string;
}

export type ExportFormat =
  | 'svg'
  | 'png'
  | 'pdf'
  | 'json'
  | 'bom-csv'
  | 'jumpers-csv'
  | 'instructions-md'
  | 'gerber-top'
  | 'gerber-bottom'
  | 'gerber-outline'
  | 'drill'
  | 'placement-csv';

export interface ExportEnvelope {
  id: string;
  projectId: string;
  layoutId: string | null;
  format: ExportFormat;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  storageKey?: string | null;
  contentType: string;
  sizeBytes?: number | null;
  checksumSha256?: string | null;
  errorMessage?: string | null;
  createdAt: string;
  completedAt?: string | null;
}

export interface BoardModelSummary {
  id: string;
  version: number;
  kind: BoardKind;
  metadata: Record<string, unknown>;
}

export interface ValidateRequest {
  boardModelId: string;
  components: Component[];
  nets: Net[];
  layout: Layout;
  options?: { allowCriticalNetClasses?: boolean };
}

export interface ValidateResponse {
  diagnostics: Diagnostic[];
  score: LayoutScore;
}

// ---- Projects --------------------------------------------------------------

export function listProjects(
  limit?: number,
  offset?: number
): Promise<ProjectListResponse> {
  const qs: string[] = [];
  if (typeof limit === 'number') qs.push(`limit=${encodeURIComponent(String(limit))}`);
  if (typeof offset === 'number') qs.push(`offset=${encodeURIComponent(String(offset))}`);
  const path = qs.length > 0 ? `/projects?${qs.join('&')}` : '/projects';
  return apiFetch<ProjectListResponse>(path);
}

export function getProject(id: string): Promise<ProjectEnvelope> {
  return apiFetch<ProjectEnvelope>(`/projects/${encodeURIComponent(id)}`);
}

export function createProject(
  name: string,
  boardModelId: string,
  document?: ProjectDocument
): Promise<ProjectEnvelope> {
  const body: ProjectCreateRequest = { name, boardModelId };
  if (document !== undefined) body.document = document;
  return apiFetch<ProjectEnvelope>('/projects', {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

export function updateProjectDocument(
  id: string,
  document: ProjectDocument,
  expectedVersion: number
): Promise<ProjectEnvelope> {
  return apiFetch<ProjectEnvelope>(`/projects/${encodeURIComponent(id)}/document`, {
    method: 'PUT',
    headers: { 'If-Match': String(expectedVersion) },
    body: JSON.stringify({ document })
  });
}

export function deleteProject(id: string): Promise<void> {
  return apiFetch<void>(`/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE'
  });
}

// ---- Revisions -------------------------------------------------------------

export function createRevision(projectId: string): Promise<RevisionEnvelope> {
  return apiFetch<RevisionEnvelope>(
    `/projects/${encodeURIComponent(projectId)}/revisions`,
    { method: 'POST' }
  );
}

export function listRevisions(projectId: string): Promise<RevisionEnvelope[]> {
  return apiFetch<RevisionEnvelope[]>(
    `/projects/${encodeURIComponent(projectId)}/revisions`
  );
}

// ---- Boards / footprints ---------------------------------------------------

export function listBoardModels(): Promise<BoardModelSummary[]> {
  return apiFetch<BoardModelSummary[]>('/board-models');
}

export function getBoardModel(id: string): Promise<AnyBoardModel & { kind: BoardKind }> {
  return apiFetch<AnyBoardModel & { kind: BoardKind }>(`/board-models/${encodeURIComponent(id)}`);
}

export function listFootprints(kind?: BoardKind): Promise<BreadboardFootprint[]> {
  const qs = kind !== undefined ? `?kind=${encodeURIComponent(kind)}` : '';
  return apiFetch<BreadboardFootprint[]>(`/footprints${qs}`);
}

// ---- Validate (synchronous, in-process on the backend) --------------------

export function validateLayout(
  boardModelId: string,
  components: Component[],
  nets: Net[],
  layout: Layout,
  options?: { allowCriticalNetClasses?: boolean }
): Promise<ValidateResponse> {
  const body: ValidateRequest = { boardModelId, components, nets, layout };
  if (options !== undefined) body.options = options;
  return apiFetch<ValidateResponse>('/validate', {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

// ---- Jobs ------------------------------------------------------------------

export interface CreateJobOptions {
  seed?: number;
  options?: SolverOptions;
  revisionId?: string;
  idempotencyKey?: string;
}

export function createJob(
  projectId: string,
  operation: SolverOperation,
  opts: CreateJobOptions = {}
): Promise<JobEnvelope> {
  const body: JobCreateRequest = { operation };
  if (opts.seed !== undefined) body.seed = opts.seed;
  if (opts.options !== undefined) body.options = opts.options;
  if (opts.revisionId !== undefined) body.revisionId = opts.revisionId;

  const headers: Record<string, string> = {};
  if (typeof opts.idempotencyKey === 'string' && opts.idempotencyKey.length > 0) {
    headers['Idempotency-Key'] = opts.idempotencyKey;
  }

  return apiFetch<JobEnvelope>(
    `/projects/${encodeURIComponent(projectId)}/jobs`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify(body)
    }
  );
}

export function getJob(id: string): Promise<JobEnvelope> {
  return apiFetch<JobEnvelope>(`/jobs/${encodeURIComponent(id)}`);
}

export function listJobEvents(id: string, afterId?: number): Promise<JobEvent[]> {
  const qs = typeof afterId === 'number' ? `?after=${encodeURIComponent(String(afterId))}` : '';
  return apiFetch<JobEvent[]>(`/jobs/${encodeURIComponent(id)}/events${qs}`);
}

export function getJobResult(id: string): Promise<JobResultEnvelope> {
  return apiFetch<JobResultEnvelope>(`/jobs/${encodeURIComponent(id)}/result`);
}

export function cancelJob(id: string): Promise<JobEnvelope> {
  return apiFetch<JobEnvelope>(`/jobs/${encodeURIComponent(id)}/cancel`, {
    method: 'POST'
  });
}

// ---- Layouts / Exports -----------------------------------------------------

export function getLayout(id: string): Promise<LayoutEnvelope> {
  return apiFetch<LayoutEnvelope>(`/layouts/${encodeURIComponent(id)}`);
}

export function createExport(layoutId: string, format: ExportFormat): Promise<ExportEnvelope> {
  return apiFetch<ExportEnvelope>(`/layouts/${encodeURIComponent(layoutId)}/exports`, {
    method: 'POST',
    body: JSON.stringify({ format })
  });
}

export function getExport(id: string): Promise<ExportEnvelope> {
  return apiFetch<ExportEnvelope>(`/exports/${encodeURIComponent(id)}`);
}

/**
 * Returns an absolute URL pointing at the export's `download` endpoint. The
 * browser fetches the bytes via a plain `<a href download>` click — the
 * caller MUST NOT `fetch()` this URL and re-stream the bytes because the
 * response body is opaque (it streams from S3 with the right Content-Type
 * and Content-Disposition set server-side). The URL is recomputed each call
 * so it picks up runtime-config changes.
 */
export function getExportDownloadUrl(id: string): string {
  const base = getRuntimeConfig().apiBaseUrl;
  const trimmedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  return `${trimmedBase}/exports/${encodeURIComponent(id)}/download`;
}

// ---- Local convenience helpers (not over the wire) ------------------------
// (Mutation helpers live in `state/project.svelte.ts` so they're co-located
// with the undo machinery.)