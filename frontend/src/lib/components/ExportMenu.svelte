<script lang="ts">
  import { createExport, getExport, getExportDownloadUrl } from '$lib/api/client';
  import { ApiError } from '$lib/api/client';
  import type { ExportEnvelope, ExportFormat } from '$lib/api/client';
  import type { BoardKind } from '$lib/types';

  type Props = {
    layoutId: string | null;
    boardKind?: BoardKind;
  };
  let { layoutId, boardKind = 'breadboard' }: Props = $props();

  const BREADBOARD_FORMATS: Array<{ id: ExportFormat; label: string; group: 'image' | 'data' | 'doc' }> = [
    { id: 'svg', label: 'SVG layout', group: 'image' },
    { id: 'png', label: 'PNG render', group: 'image' },
    { id: 'pdf', label: 'PDF guide', group: 'image' },
    { id: 'json', label: 'Project JSON', group: 'data' },
    { id: 'bom-csv', label: 'BOM (CSV)', group: 'data' },
    { id: 'jumpers-csv', label: 'Wires (CSV)', group: 'data' },
    { id: 'instructions-md', label: 'Build instructions', group: 'doc' }
  ];
  const PERFBOARD_FORMATS: Array<{ id: ExportFormat; label: string; group: 'image' | 'data' | 'doc' }> = [
    { id: 'svg', label: 'SVG layout', group: 'image' },
    { id: 'png', label: 'PNG render', group: 'image' },
    { id: 'pdf', label: 'PDF guide', group: 'image' },
    { id: 'json', label: 'Project JSON', group: 'data' },
    { id: 'bom-csv', label: 'BOM (CSV)', group: 'data' },
    { id: 'gerber-top', label: 'Gerber (top copper)', group: 'data' },
    { id: 'gerber-bottom', label: 'Gerber (bottom copper)', group: 'data' },
    { id: 'gerber-outline', label: 'Gerber (outline)', group: 'data' },
    { id: 'drill', label: 'Drill (Excellon)', group: 'data' },
    { id: 'placement-csv', label: 'Pick-and-place', group: 'data' },
    { id: 'instructions-md', label: 'Build instructions', group: 'doc' }
  ];
  const FORMATS = $derived(boardKind === 'perfboard' ? PERFBOARD_FORMATS : BREADBOARD_FORMATS);

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

  function groupLabel(group: 'image' | 'data' | 'doc'): string {
    switch (group) {
      case 'image':
        return 'Image';
      case 'data':
        return 'Data';
      case 'doc':
        return 'Doc';
    }
  }
</script>

<section class="export-menu" aria-label="Export">
  {#if layoutId === null}
    <p class="empty">Run a Solve to enable export.</p>
  {:else}
    <div class="hint">
      Each format renders server-side; the build waits for the worker before the download link appears.
    </div>
    {#each ['image', 'data', 'doc'] as group (group)}
      {@const items = FORMATS.filter((f) => f.group === group)}
      {#if items.length > 0}
        <div class="group">
          <header class="group-head">
            <span class="group-label">{groupLabel(group as 'image' | 'data' | 'doc')}</span>
          </header>
          <ul>
            {#each items as fmt (fmt.id)}
              {@const env = exportsByFormat[fmt.id]}
              {@const isReady = env?.status === 'succeeded' && typeof env.id === 'string'}
              {@const isPending = env?.status === 'pending' || env?.status === 'running'}
              {@const isFailed = env?.status === 'failed'}
              {@const url = isReady ? getExportDownloadUrl(env.id) : null}
              <li>
                <button
                  type="button"
                  class="export-btn"
                  class:ready={isReady}
                  class:pending={isPending}
                  class:failed={isFailed}
                  disabled={isPending}
                  onclick={() => void startExport(fmt.id)}
                  title={`Generate ${fmt.label}`}
                >
                  <span class="format-label">{fmt.label}</span>
                  <span class="format-state mono">
                    {#if isPending}rendering…
                    {:else if isReady}ready
                    {:else if isFailed}failed
                    {:else}generate
                    {/if}
                  </span>
                </button>
                {#if url !== null}
                  <a class="download-link" href={url} download>
                    download
                  </a>
                {/if}
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {/each}
  {/if}
  {#if lastError !== null}
    <p class="error mono">{lastError}</p>
  {/if}
</section>

<style>
  .export-menu {
    padding: 0;
    font-size: var(--fs-12);
  }

  .hint {
    margin: 0;
    padding: 0 var(--sp-3) var(--sp-3);
    color: var(--ink-3);
    font-size: var(--fs-11);
    line-height: 1.4;
  }

  .empty {
    color: var(--ink-3);
    font-style: italic;
    margin: 0;
    padding: var(--sp-3);
  }

  .group + .group {
    margin-top: var(--sp-3);
  }

  .group-head {
    padding: 0 var(--sp-3) 6px;
  }

  .group-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    font-weight: 600;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }

  li {
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid var(--paper-edge);
  }

  li:last-child {
    border-bottom: none;
  }

  .export-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px var(--sp-3);
    background: transparent;
    border: none;
    border-radius: 0;
    color: var(--ink-1);
    text-align: left;
    font-size: var(--fs-12);
    cursor: pointer;
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .export-btn:hover:not(:disabled) {
    background: var(--paper-2);
  }

  .export-btn:disabled {
    cursor: default;
    opacity: 0.85;
  }

  .export-btn.pending {
    background: var(--accent-soft);
  }

  .export-btn.ready {
    color: var(--ok);
  }

  .export-btn.failed {
    color: var(--sev-error);
    background: var(--sev-error-soft);
  }

  .format-label {
    font-weight: 500;
  }

  .format-state {
    font-size: 10px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .export-btn.pending .format-state {
    color: var(--accent-1);
  }
  .export-btn.ready .format-state {
    color: var(--ok);
  }
  .export-btn.failed .format-state {
    color: var(--sev-error);
  }

  .download-link {
    display: inline-flex;
    align-items: center;
    padding: 0 12px;
    color: var(--accent-1);
    font-size: var(--fs-11);
    font-weight: 500;
    text-decoration: none;
    border-left: 1px solid var(--paper-edge);
  }

  .download-link:hover {
    background: var(--accent-soft);
    text-decoration: none;
  }

  .error {
    color: var(--sev-error);
    margin: var(--sp-2) var(--sp-3) 0;
    font-size: var(--fs-11);
  }
</style>