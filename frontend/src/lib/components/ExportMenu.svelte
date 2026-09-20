<script lang="ts">
  import { createExport, getExport, getExportDownloadUrl } from '$lib/api/client';
  import { ApiError } from '$lib/api/client';
  import type { ExportEnvelope, ExportFormat } from '$lib/api/client';

  type Props = {
    layoutId: string | null;
  };
  let { layoutId }: Props = $props();

  // Human labels for the seven supported export formats. The id matches
  // the backend's `ExportFormat` literal so `createExport(layoutId, id)`
  // passes through unchanged.
  const FORMATS: Array<{ id: ExportFormat; label: string }> = [
    { id: 'svg', label: 'SVG' },
    { id: 'png', label: 'PNG' },
    { id: 'pdf', label: 'PDF' },
    { id: 'json', label: 'Project JSON' },
    { id: 'bom-csv', label: 'BOM CSV' },
    { id: 'jumpers-csv', label: 'Jumpers CSV' },
    { id: 'instructions-md', label: 'Istruzioni Markdown' }
  ];

  // Per-format export state. We track all in-flight / finished jobs so the
  // user can trigger every format in parallel without losing status.
  let exportsByFormat = $state<Partial<Record<ExportFormat, ExportEnvelope>>>({});
  let pollHandles = $state<Partial<Record<ExportFormat, ReturnType<typeof setInterval>>>>({});
  let lastError = $state<string | null>(null);

  function stopPolling(format: ExportFormat): void {
    const handle = pollHandles[format];
    if (handle !== undefined) {
      clearInterval(handle);
      const next: Partial<Record<ExportFormat, ReturnType<typeof setInterval>>> = { ...pollHandles };
      delete next[format];
      pollHandles = next;
    }
  }

  function startPolling(format: ExportFormat, exportId: string): void {
    const handle = setInterval(() => {
      void (async () => {
        try {
          const next = await getExport(exportId);
          exportsByFormat = { ...exportsByFormat, [format]: next };
          if (next.status === 'succeeded' || next.status === 'failed') {
            stopPolling(format);
          }
        } catch (err) {
          lastError = err instanceof ApiError ? err.message : 'Polling failed.';
          stopPolling(format);
        }
      })();
    }, 1000);
    pollHandles = { ...pollHandles, [format]: handle };
  }

  async function startExport(format: ExportFormat): Promise<void> {
    if (layoutId === null) return;
    lastError = null;
    try {
      const env = await createExport(layoutId, format);
      exportsByFormat = { ...exportsByFormat, [format]: env };
      if (env.status === 'pending' || env.status === 'running') {
        startPolling(format, env.id);
      }
    } catch (err) {
      lastError = err instanceof ApiError ? err.message : 'Export failed.';
    }
  }
</script>

<section class="export-menu" aria-label="Export">
  <header>
    <h2>Export</h2>
  </header>
  {#if layoutId === null}
    <p class="empty">No layout yet</p>
  {:else}
    <ul>
      {#each FORMATS as fmt (fmt.id)}
        {@const env = exportsByFormat[fmt.id]}
        {@const inFlight = env?.status === 'pending' || env?.status === 'running'}
        {@const url =
          env !== undefined && env.status === 'succeeded'
            ? getExportDownloadUrl(env.id)
            : null}
        <li>
          <button
            type="button"
            disabled={inFlight}
            onclick={() => void startExport(fmt.id)}
          >
            {fmt.label}
          </button>
          {#if env}
            <span class={`status status-${env.status}`}>{env.status}</span>
          {/if}
          {#if url !== null}
            <a class="download" href={url} download>Scarica</a>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  {#if lastError !== null}
    <p class="error">{lastError}</p>
  {/if}
</section>

<style>
  .export-menu {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    font-size: 13px;
  }

  h2 {
    margin: 0;
    font-size: 14px;
  }

  .empty {
    color: var(--color-muted);
    font-style: italic;
    margin: 0;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  button {
    padding: 4px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-border);
    background: var(--color-bg);
  }

  button:hover:not(:disabled) {
    background: var(--color-accent);
    color: white;
    border-color: var(--color-accent);
  }

  .status {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .status-pending,
  .status-running {
    color: var(--color-warning);
  }
  .status-succeeded {
    color: var(--color-info);
  }
  .status-failed {
    color: var(--color-error);
  }

  .download {
    font-size: 12px;
  }

  .error {
    color: var(--color-error);
    margin: 0;
  }
</style>