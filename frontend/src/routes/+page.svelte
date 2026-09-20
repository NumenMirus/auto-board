<script lang="ts">
  import { apiFetch, ApiError } from '$lib/api/client';
  import type { ProjectDocument, ProjectListResponse } from '$lib/types';

  interface CreateProjectResponse {
    id: string;
    name: string;
    draftVersion: number;
  }

  let projects = $state<ProjectListResponse | null>(null);
  let loadError = $state<string | null>(null);
  let uploadStatus = $state<string | null>(null);
  let isUploading = $state(false);

  async function refresh(): Promise<void> {
    loadError = null;
    try {
      projects = await apiFetch<ProjectListResponse>('/projects');
    } catch (err) {
      loadError = err instanceof ApiError ? err.message : 'Failed to load projects.';
    }
  }

  $effect(() => {
    void refresh();
  });

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
      const created = await apiFetch<CreateProjectResponse>('/projects', {
        method: 'POST',
        body: JSON.stringify({ name: doc.name, document: doc })
      });
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

  <div class="upload">
    <label for="project-upload">New project from JSON:</label>
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
      <p class="empty">No projects yet. Upload a netlist JSON to create one.</p>
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