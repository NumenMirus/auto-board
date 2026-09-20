<script lang="ts">
  import { onDestroy } from 'svelte';
  import { cancelJob, getJob, getJobResult } from '$lib/api/client';
  import { ApiError } from '$lib/api/client';
  import type { JobEnvelope } from '$lib/api/client';
  import type { Diagnostic, Layout, LayoutScore } from '$lib/types';

  type Props = {
    jobId: string | null;
    onApply: (result: {
      layout: Layout;
      score: LayoutScore;
      diagnostics: Diagnostic[];
    }) => void;
    // Optional: fires every poll cycle with the latest job envelope, so
    // the parent page can keep its own snapshot (e.g. `resultLayoutId`)
    // fresh for downstream UI like ExportMenu.
    onJobUpdate?: ((job: JobEnvelope) => void) | undefined;
  };
  let { jobId, onApply, onJobUpdate = undefined }: Props = $props();

  // Snapshot of the latest job we polled — the template reads from this
  // instead of the global store so the same component can be embedded in
  // panels, modals, etc. without coupling to projectStore.
  let status = $state<string | null>(null);
  let percent = $state<number>(0);
  let phase = $state<string | null>(null);
  let errorMessage = $state<string | null>(null);

  let pollHandle: ReturnType<typeof setInterval> | null = null;
  let cancelledFlag = $state(false);
  let applying = $state(false);
  let applyError = $state<string | null>(null);

  function stopPolling(): void {
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  async function tick(): Promise<void> {
    if (jobId === null) return;
    try {
      const job = await getJob(jobId);
      status = job.status;
      percent = job.progressPercent;
      phase = job.progressPhase;
      errorMessage = job.errorMessage ?? null;
      onJobUpdate?.(job);
      if (
        job.status === 'succeeded' ||
        job.status === 'failed' ||
        job.status === 'cancelled'
      ) {
        stopPolling();
      }
    } catch (err) {
      status = 'failed';
      errorMessage = err instanceof ApiError ? err.message : 'Polling failed.';
      stopPolling();
    }
  }

  $effect(() => {
    // Track the latest jobId; start/stop polling accordingly. The effect
    // re-runs whenever jobId changes, so a fresh job kicks a new
    // interval and the old one is cleaned up before this one starts.
    stopPolling();
    cancelledFlag = false;
    applying = false;
    applyError = null;
    status = null;
    percent = 0;
    phase = null;
    errorMessage = null;
    if (jobId === null) return;
    void tick();
    pollHandle = setInterval(() => {
      void tick();
    }, 1000);
    return () => {
      stopPolling();
    };
  });

  onDestroy(stopPolling);

  async function onCancelClick(): Promise<void> {
    if (jobId === null) return;
    cancelledFlag = true;
    try {
      await cancelJob(jobId);
    } catch (err) {
      errorMessage = err instanceof ApiError ? err.message : 'Cancel failed.';
    }
  }

  async function onApplyClick(): Promise<void> {
    if (jobId === null) return;
    applying = true;
    applyError = null;
    try {
      const result = await getJobResult(jobId);
      onApply({
        layout: result.layout,
        score: result.score,
        diagnostics: result.diagnostics
      });
    } catch (err) {
      applyError = err instanceof ApiError ? err.message : 'Failed to load result.';
    } finally {
      applying = false;
    }
  }

  const finished = $derived(
    status === 'succeeded' || status === 'failed' || status === 'cancelled'
  );
  const showApply = $derived(status === 'succeeded');
  const showCancel = $derived(status === 'queued' || status === 'running');
</script>

{#if jobId !== null}
  <section class="job-progress" aria-label="Solver job progress">
    <header class="header">
      <span class="status status-{status ?? 'pending'}">{status ?? 'pending'}</span>
      <span class="phase">{phase ?? ''}</span>
    </header>
    <div class="bar-track">
      <div class="bar-fill" style:width="{Math.max(0, Math.min(100, percent))}%"></div>
    </div>
    <div class="meta">{percent}%</div>
    {#if errorMessage !== null}
      <p class="error">{errorMessage}</p>
    {/if}
    {#if applyError !== null}
      <p class="error">{applyError}</p>
    {/if}
    <div class="actions">
      {#if showCancel}
        <button type="button" onclick={onCancelClick} disabled={cancelledFlag}>
          Cancel
        </button>
      {/if}
      {#if showApply}
        <button type="button" onclick={onApplyClick} disabled={applying}>
          {applying ? 'Applying…' : 'Apply to draft'}
        </button>
      {/if}
    </div>
    {#if finished && !showApply && !showCancel}
      <p class="hint">Job finished. Pick another action.</p>
    {/if}
  </section>
{/if}

<style>
  .job-progress {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: 13px;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .status {
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.04em;
  }

  .status-succeeded {
    color: var(--color-info);
  }
  .status-failed,
  .status-cancelled {
    color: var(--color-error);
  }
  .status-running,
  .status-queued {
    color: var(--color-warning);
  }

  .bar-track {
    height: 8px;
    background: var(--color-border);
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: var(--color-accent);
    transition: width 200ms linear;
  }

  .meta {
    color: var(--color-muted);
    font-variant-numeric: tabular-nums;
  }

  .error {
    color: var(--color-error);
    margin: 0;
  }

  .hint {
    color: var(--color-muted);
    margin: 0;
    font-style: italic;
  }

  .actions {
    display: flex;
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
</style>