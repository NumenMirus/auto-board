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

  // When the board-type toggle changes, re-pick the first board of that
  // kind so the dependent <select> never points at a mismatched id.
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
      // Sanity check: must be a ProjectDocument (camelCase on the wire).
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
  <h1>Projects</h1>

  <div class="create-panel">
    <h2>New project</h2>
    <div class="create-form">
      <label class="field">
        <span>Name</span>
        <input
          type="text"
          bind:value={newProjectName}
          placeholder="My circuit"
          disabled={isCreating}
        />
      </label>

      <div class="field">
        <span id="board-type-label">Board type</span>
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
        <span>Board model</span>
        {#if boardsError}
          <span class="status error">{boardsError}</span>
        {:else if boardModels === null}
          <span class="status">Loading boards…</span>
        {:else if boardsForKind.length === 0}
          <span class="status">No {newProjectKind} models available.</span>
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
        class="create-button"
        onclick={onCreateProject}
        disabled={isCreating || newProjectName.trim() === '' || newProjectBoardId === null}
      >
        {isCreating ? 'Creating…' : 'Create'}
      </button>
    </div>
    {#if createError}
      <p class="status error">{createError}</p>
    {/if}
  </div>

  <div class="upload">
    <label for="project-upload">Or import from JSON:</label>
    <input
      id="project-upload"
      type="file"
      accept="application/json,.json"
      onchange={onFileChange}
      disabled={isUploading}
    />
    {#if uploadStatus}
      <span class="status">{uploadStatus}</span>
    {/if}
  </div>

  {#if loadError}
    <p class="error">Error: {loadError}</p>
  {/if}

  {#if projects === null && !loadError}
    <p>Loading…</p>
  {:else if projects}
    {#if projects.items.length === 0}
      <p class="empty">No projects yet. Create one above or import a netlist JSON.</p>
    {:else}
      <ul class="project-list">
        {#each projects.items as project (project.id)}
          <li>
            <a href={`/projects/${project.id}`}>
              <strong>{project.name}</strong>
              <span class="meta">rev {project.draftVersion}</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .page {
    padding: var(--space-4);
    max-width: 900px;
    margin: 0 auto;
    width: 100%;
  }

  h1 {
    margin: 0 0 var(--space-3);
  }

  h2 {
    margin: 0 0 var(--space-3);
    font-size: 15px;
    font-weight: 600;
  }

  .create-panel {
    padding: var(--space-4);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    margin-bottom: var(--space-3);
  }

  .create-form {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: var(--space-3);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    font-size: 13px;
    color: var(--color-muted);
  }

  .field input[type='text'],
  .field select {
    font-size: 14px;
    color: var(--color-fg);
    padding: 6px 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    min-width: 220px;
  }

  .kind-toggle {
    display: inline-flex;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .kind-toggle button {
    padding: 6px 14px;
    border: none;
    background: var(--color-bg);
    color: var(--color-fg);
    font-size: 14px;
  }

  .kind-toggle button + button {
    border-left: 1px solid var(--color-border);
  }

  .kind-toggle button.active {
    background: var(--color-accent);
    color: white;
  }

  .kind-toggle button:hover:not(.active):not(:disabled) {
    background: var(--color-surface);
  }

  .kind-toggle button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .create-button {
    padding: 7px 16px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-accent);
    background: var(--color-accent);
    color: white;
    font-size: 14px;
    font-weight: 500;
  }

  .create-button:hover:not(:disabled) {
    opacity: 0.9;
  }

  .create-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .upload {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-3);
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-4);
  }

  .status {
    color: var(--color-muted);
    font-size: 14px;
  }

  .status.error {
    color: var(--color-error);
  }

  .error {
    color: var(--color-error);
  }

  .empty {
    color: var(--color-muted);
    font-style: italic;
  }

  .project-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .project-list li {
    border-bottom: 1px solid var(--color-border);
  }

  .project-list a {
    display: flex;
    justify-content: space-between;
    padding: var(--space-2) var(--space-3);
  }

  .project-list a:hover {
    background: var(--color-surface);
    text-decoration: none;
  }

  .meta {
    color: var(--color-muted);
    font-size: 14px;
  }
</style>
