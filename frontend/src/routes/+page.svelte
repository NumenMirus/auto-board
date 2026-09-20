<script lang="ts">
  import { apiFetch, ApiError, listBoardModels, createProject } from '$lib/api/client';
  import type { BoardModelSummary } from '$lib/api/client';
  import type { BoardKind, ProjectDocument, ProjectListResponse } from '$lib/types';
  import { goto } from '$app/navigation';

  let projects = $state<ProjectListResponse | null>(null);
  let loadError = $state<string | null>(null);
  let uploadStatus = $state<string | null>(null);
  let isUploading = $state(false);

  // ---- New-project form --------------------------------------------------
  let boardModels = $state<BoardModelSummary[] | null>(null);
  let boardsError = $state<string | null>(null);
  let newProjectName = $state('');
  let newProjectKind = $state<BoardKind>('breadboard');
  let newProjectBoardId = $state<string | null>(null);
  let isCreating = $state(false);
  let createError = $state<string | null>(null);

  const boardsForKind = $derived(
    (boardModels ?? []).filter((b) => b.kind === newProjectKind)
  );

  async function refresh(): Promise<void> {
    loadError = null;
    try {
      projects = await apiFetch<ProjectListResponse>('/projects');
    } catch (err) {
      loadError = err instanceof ApiError ? err.message : 'Failed to load projects.';
    }
  }

  async function refreshBoards(): Promise<void> {
    boardsError = null;
    try {
      boardModels = await listBoardModels();
      const firstForKind = boardModels.find((b) => b.kind === newProjectKind);
      newProjectBoardId = firstForKind?.id ?? null;
    } catch (err) {
      boardsError = err instanceof ApiError ? err.message : 'Failed to load board models.';
    }
  }

  $effect(() => {
    void refresh();
    void refreshBoards();
  });

  function onKindChange(kind: BoardKind): void {
    newProjectKind = kind;
    const firstForKind = (boardModels ?? []).find((b) => b.kind === kind);
    newProjectBoardId = firstForKind?.id ?? null;
  }

  async function onCreateProject(): Promise<void> {
    const name = newProjectName.trim();
    if (name === '' || newProjectBoardId === null) return;
    isCreating = true;
    createError = null;
    try {
      const created = await createProject(name, newProjectBoardId);
      await goto(`/projects/${created.id}`);
    } catch (err) {
      createError = err instanceof ApiError ? err.message : 'Failed to create project.';
    } finally {
      isCreating = false;
    }
  }

  async function onFileChange(event: Event): Promise<void> {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    isUploading = true;
    uploadStatus = `Reading ${file.name}…`;
    try {
      const text = await file.text();
      const parsed: unknown = JSON.parse(text);
      if (
        !parsed ||
        typeof parsed !== 'object' ||
        (parsed as { format?: unknown }).format !== 'autobreadboard-project'
      ) {
        throw new Error('File is not an autobreadboard-project document.');
      }
      const doc = parsed as ProjectDocument;
      uploadStatus = `Creating project "${doc.name}"…`;
      const created = await apiFetch<{ id: string; name: string; draftVersion: number }>(
        '/projects',
        {
          method: 'POST',
          body: JSON.stringify({ name: doc.name, boardModelId: doc.board.modelId, document: doc })
        }
      );
      uploadStatus = `Created project ${created.id}.`;
      await refresh();
    } catch (err) {
      uploadStatus =
        err instanceof ApiError
          ? `Upload failed: ${err.message}`
          : err instanceof Error
            ? `Upload failed: ${err.message}`
            : 'Upload failed.';
    } finally {
      isUploading = false;
      input.value = '';
    }
  }
</script>

<section class="page">
  <header class="page-head">
    <div>
      <span class="eyebrow mono">Workbench</span>
      <h1>Projects</h1>
      <p class="lede">
        Drop in a netlist JSON, pick a board, and AutoBoard will propose a layout
        you can edit, verify, and print as an assembly guide.
      </p>
    </div>

    <div class="hero-stats mono" aria-hidden="true">
      <div class="stat">
        <span class="stat-value">{projects?.total ?? '—'}</span>
        <span class="stat-label">projects</span>
      </div>
      <div class="stat">
        <span class="stat-value">{boardModels?.length ?? '—'}</span>
        <span class="stat-label">boards</span>
      </div>
    </div>
  </header>

  <div class="layout-grid">
    <!-- ===== New project panel ===== -->
    <section class="panel new-project">
      <header class="panel-header">
        <h2>New project</h2>
        <span class="panel-meta mono">step 1 / 2</span>
      </header>

      <div class="form">
        <label class="field field-name">
          <span class="field-label">Name</span>
          <input
            type="text"
            bind:value={newProjectName}
            placeholder="74HC14 oscillator"
            disabled={isCreating}
          />
        </label>

        <div class="field field-kind">
          <span class="field-label" id="board-type-label">Board</span>
          <div class="kind-toggle" role="radiogroup" aria-labelledby="board-type-label">
            <button
              type="button"
              role="radio"
              aria-checked={newProjectKind === 'breadboard'}
              class:active={newProjectKind === 'breadboard'}
              disabled={isCreating}
              onclick={() => onKindChange('breadboard')}
            >
              Breadboard
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={newProjectKind === 'perfboard'}
              class:active={newProjectKind === 'perfboard'}
              disabled={isCreating}
              onclick={() => onKindChange('perfboard')}
            >
              Perfboard
            </button>
          </div>
        </div>

        <label class="field">
          <span class="field-label">Model</span>
          {#if boardsError}
            <span class="status error mono">{boardsError}</span>
          {:else if boardModels === null}
            <span class="status mono">Loading boards…</span>
          {:else if boardsForKind.length === 0}
            <span class="status mono">No {newProjectKind} models available.</span>
          {:else}
            <select bind:value={newProjectBoardId} disabled={isCreating}>
              {#each boardsForKind as board (board.id)}
                <option value={board.id}>{board.id}</option>
              {/each}
            </select>
          {/if}
        </label>

        <button
          type="button"
          class="primary create"
          onclick={onCreateProject}
          disabled={isCreating || newProjectName.trim() === '' || newProjectBoardId === null}
        >
          {isCreating ? 'Creating…' : 'Open empty board'}
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path d="M3 7h8M7 3l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>

        {#if createError}
          <p class="status error mono">{createError}</p>
        {/if}
      </div>
    </section>

    <!-- ===== Import panel ===== -->
    <section class="panel import">
      <header class="panel-header">
        <h2>Import netlist</h2>
        <span class="panel-meta mono">step 1 / 2</span>
      </header>

      <p class="hint">
        Drop a JSON netlist exported from AutoBoard or hand-authored against
        the wire format. We import the components and nets into a fresh
        project; the layout comes after.
      </p>

      <label class="upload">
        <input
          id="project-upload"
          type="file"
          accept="application/json,.json"
          onchange={onFileChange}
          disabled={isUploading}
        />
        <span class="upload-cta">
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <path d="M7 2v8M3 6l4-4 4 4M2 12h10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          <span>{isUploading ? 'Importing…' : 'Choose JSON file'}</span>
        </span>
        <span class="upload-help mono">.json — autobreadboard-project</span>
      </label>

      {#if uploadStatus}
        <p class="status mono">{uploadStatus}</p>
      {/if}
    </section>
  </div>

  {#if loadError}
    <p class="error mono">{loadError}</p>
  {/if}

  <!-- ===== Project list ===== -->
  <section class="projects-section">
    <header class="section-head">
      <span class="eyebrow mono">Recent</span>
      <h2>Saved projects</h2>
      <span class="section-meta mono">
        {projects?.items.length ?? 0} of {projects?.total ?? 0}
      </span>
    </header>

    {#if projects === null && !loadError}
      <p class="loading mono">Loading…</p>
    {:else if projects && projects.items.length === 0}
      <div class="empty-state">
        <div class="empty-art" aria-hidden="true">
          <svg viewBox="0 0 80 30" width="120" height="46">
            <rect x="2" y="6" width="76" height="18" rx="1.5" fill="none" stroke="currentColor" stroke-width="0.6" opacity="0.4" />
            {#each Array(6) as _, c (c)}
              <line x1={(4 + c * 12.5).toFixed(2)} x2={(4 + c * 12.5).toFixed(2)} y1="6" y2="24" stroke="currentColor" stroke-width="0.3" opacity="0.4" />
            {/each}
            {#each Array(5) as _, r (r)}
              <circle cx={(8 + r * 3).toFixed(2)} cy={(12 + r * 2).toFixed(2)} r="0.6" fill="currentColor" opacity="0.45" />
            {/each}
          </svg>
        </div>
        <h3>No projects yet</h3>
        <p>Start with an empty board above, or drop in a netlist JSON.</p>
      </div>
    {:else if projects}
      <ul class="project-list">
        {#each projects.items as project (project.id)}
          <li>
            <a href={`/projects/${project.id}`}>
              <div class="project-main">
                <span class="project-name">{project.name}</span>
                <span class="project-id mono">{project.id}</span>
              </div>
              <div class="project-meta mono">
                <span class="meta-tag">rev {project.draftVersion}</span>
                <span class="meta-arrow" aria-hidden="true">→</span>
              </div>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  </section>
</section>

<style>
  .page {
    max-width: 1080px;
    width: 100%;
    margin: 0 auto;
    padding: var(--sp-8) var(--sp-6) var(--sp-10);
    display: flex;
    flex-direction: column;
    gap: var(--sp-8);
  }

  /* ----- Page head ----- */
  .page-head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--sp-6);
  }

  .eyebrow {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-3);
    margin-bottom: 6px;
  }

  h1 {
    margin: 0;
    font-size: var(--fs-32);
    font-weight: 600;
    color: var(--ink-1);
    letter-spacing: -0.02em;
  }

  .lede {
    margin: 8px 0 0;
    color: var(--ink-2);
    font-size: var(--fs-14);
    max-width: 56ch;
    line-height: 1.5;
  }

  .hero-stats {
    display: flex;
    gap: var(--sp-3);
    padding: var(--sp-3) var(--sp-4);
    background: var(--paper-2);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-3);
  }

  .stat {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    min-width: 64px;
  }

  .stat + .stat {
    border-left: 1px solid var(--paper-edge);
    padding-left: var(--sp-3);
  }

  .stat-value {
    font-size: var(--fs-20);
    font-weight: 600;
    color: var(--ink-1);
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .stat-label {
    font-size: 10px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  /* ----- Layout grid ----- */
  .layout-grid {
    display: grid;
    grid-template-columns: 1.1fr 1fr;
    gap: var(--sp-4);
  }

  @media (max-width: 800px) {
    .layout-grid {
      grid-template-columns: 1fr;
    }
  }

  /* ----- Panels ----- */
  .panel {
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-3);
    box-shadow: var(--sh-1);
    overflow: hidden;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 10px var(--sp-4);
    background: var(--paper-2);
    border-bottom: 1px solid var(--paper-edge);
  }

  .panel-header h2 {
    font-size: var(--fs-12);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-2);
    flex: 1;
  }

  .panel-meta {
    font-size: var(--fs-11);
    color: var(--ink-3);
    padding: 1px 6px;
    border-radius: var(--r-1);
    background: var(--paper-1);
    border: 1px solid var(--paper-edge);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* ----- New project form ----- */
  .form {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-3) var(--sp-4);
    padding: var(--sp-4);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .field-name {
    grid-column: 1 / -1;
  }

  .field-label {
    color: var(--ink-3);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-weight: 500;
  }

  .field input[type='text'],
  .field select {
    width: 100%;
    font-size: var(--fs-14);
    padding: 8px 10px;
  }

  .kind-toggle {
    display: inline-flex;
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    overflow: hidden;
    background: var(--paper-1);
    align-self: flex-start;
  }

  .kind-toggle button {
    padding: 8px 16px;
    border: none;
    background: transparent;
    color: var(--ink-2);
    font-size: var(--fs-13);
    font-weight: 500;
    border-radius: 0;
  }

  .kind-toggle button + button {
    border-left: 1px solid var(--paper-edge);
  }

  .kind-toggle button:hover:not(.active):not(:disabled) {
    background: var(--paper-2);
  }

  .kind-toggle button.active {
    background: var(--accent-1);
    color: #fff;
  }

  .kind-toggle button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .create {
    grid-column: 1 / -1;
    justify-self: start;
    padding: 8px 16px;
    font-size: var(--fs-13);
    font-weight: 500;
  }

  .create svg {
    transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .create:hover:not(:disabled) svg {
    transform: translateX(2px);
  }

  .status {
    color: var(--ink-3);
    font-size: var(--fs-12);
  }

  .status.error {
    color: var(--sev-error);
  }

  /* ----- Import panel ----- */
  .hint {
    margin: 0;
    padding: var(--sp-3) var(--sp-4) 0;
    color: var(--ink-2);
    font-size: var(--fs-12);
    line-height: 1.5;
  }

  .upload {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: var(--sp-3) var(--sp-4) var(--sp-4);
    padding: var(--sp-4);
    border: 1px dashed var(--paper-edge);
    border-radius: var(--r-2);
    background: var(--paper-1);
    cursor: pointer;
    transition: border-color 180ms cubic-bezier(0.16, 1, 0.3, 1), background-color 180ms
      cubic-bezier(0.16, 1, 0.3, 1);
  }

  .upload:hover {
    border-color: var(--accent-1);
    background: var(--accent-soft);
  }

  .upload input[type='file'] {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  .upload-cta {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--accent-1);
    font-weight: 500;
    font-size: var(--fs-13);
  }

  .upload-help {
    font-size: 10px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  /* ----- Projects section ----- */
  .projects-section {
    display: flex;
    flex-direction: column;
    gap: var(--sp-3);
  }

  .section-head {
    display: flex;
    align-items: baseline;
    gap: var(--sp-3);
    padding: 0 2px;
  }

  .section-head h2 {
    margin: 0;
    font-size: var(--fs-17);
    font-weight: 600;
    color: var(--ink-1);
    flex: 1;
  }

  .section-meta {
    font-size: var(--fs-11);
    color: var(--ink-3);
    padding: 1px 6px;
    border-radius: var(--r-1);
    background: var(--paper-2);
    border: 1px solid var(--paper-edge);
  }

  .loading {
    color: var(--ink-3);
    font-style: italic;
    padding: var(--sp-4);
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding: var(--sp-10) var(--sp-4);
    background: var(--paper-0);
    border: 1px dashed var(--paper-edge);
    border-radius: var(--r-3);
    color: var(--ink-3);
  }

  .empty-art {
    color: var(--ink-3);
    margin-bottom: var(--sp-3);
  }

  .empty-state h3 {
    margin: 0;
    font-size: var(--fs-15);
    color: var(--ink-2);
  }

  .empty-state p {
    margin: 6px 0 0;
    font-size: var(--fs-13);
    color: var(--ink-3);
  }

  .project-list {
    list-style: none;
    margin: 0;
    padding: 0;
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-3);
    box-shadow: var(--sh-1);
    overflow: hidden;
  }

  .project-list li + li {
    border-top: 1px solid var(--paper-edge);
  }

  .project-list a {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-3);
    padding: 12px var(--sp-4);
    color: var(--ink-1);
    text-decoration: none;
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .project-list a:hover {
    background: var(--paper-2);
    text-decoration: none;
  }

  .project-main {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .project-name {
    font-size: var(--fs-14);
    font-weight: 500;
    color: var(--ink-1);
  }

  .project-id {
    font-size: 10px;
    color: var(--ink-3);
    letter-spacing: 0.02em;
  }

  .project-meta {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  .meta-tag {
    color: var(--ink-3);
    font-size: var(--fs-11);
    padding: 2px 8px;
    border-radius: var(--r-pill);
    background: var(--paper-2);
    border: 1px solid var(--paper-edge);
  }

  .meta-arrow {
    color: var(--ink-3);
    transition: color 120ms cubic-bezier(0.16, 1, 0.3, 1), transform 120ms
      cubic-bezier(0.16, 1, 0.3, 1);
  }

  .project-list a:hover .meta-arrow {
    color: var(--accent-1);
    transform: translateX(2px);
  }

  .error {
    color: var(--sev-error);
    margin: 0;
    padding: var(--sp-3);
    border: 1px solid var(--sev-error-line);
    background: var(--sev-error-soft);
    border-radius: var(--r-2);
    font-size: var(--fs-12);
  }
</style>