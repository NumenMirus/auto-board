<script lang="ts">
  import type { JobEnvelope } from '$lib/api/client';
  import { cancelJob, getJob, getJobResult } from '$lib/api/client';
  import { ApiError } from '$lib/api/client';
  import type { Layout, LayoutScore, Diagnostic, TraceLayout } from '$lib/types';

  type Props = {
    jobId: string | null;
    onApply?: ((result: { layout: Layout | TraceLayout; score: LayoutScore; diagnostics: Diagnostic[] }) => void) | undefined;
    onJobUpdate?: ((job: JobEnvelope) => void) | undefined;
  };
  let { jobId, onApply = undefined, onJobUpdate = undefined }: Props = $props();

  let status = $state<string | null>(null);
  let percent = $state(0);
  let phase = $state<string | null>(null);
  let errorMessage = $state<string | null>(null);
  let finished = $state(false);
  let showApply = $state(false);
  let showCancel = $state(false);
  let cancelledFlag = $state(false);
  let applyError = $state<string | null>(null);
  let applying = $state(false);

  let pollHandle: ReturnType<typeof setInterval> | null = null;

  function stopPolling(): void {
    if (pollHandle !== null) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  }

  $effect(() => {
    if (jobId === null) {
      status = null;
      percent = 0;
      phase = null;
      errorMessage = null;
      finished = false;
      showApply = false;
      showCancel = false;
      cancelledFlag = false;
      applyError = null;
      applying = false;
      stopPolling();
      return;
    }

    stopPolling();
    status = 'queued';
    percent = 0;
    phase = 'queued';
    errorMessage = null;
    finished = false;
    showApply = false;
    showCancel = true;
    cancelledFlag = false;
    applyError = null;

    pollHandle = setInterval(() => {
      void (async () => {
        try {
          const job = await getJob(jobId);
          status = job.status;
          percent = job.progressPercent;
          phase = job.progressPhase;
          if (typeof job.errorMessage === 'string' && job.errorMessage.length > 0) {
            errorMessage = job.errorMessage;
          }
          finished = job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled';
          showCancel = job.status === 'queued' || job.status === 'running';
          showApply = job.status === 'succeeded' && typeof job.resultLayoutId === 'string';
          onJobUpdate?.(job);
          if (finished) {
            stopPolling();
          }
        } catch (err) {
          errorMessage = err instanceof ApiError ? err.message : 'Polling failed.';
          finished = true;
          stopPolling();
        }
      })();
    }, 1000);
  });

  async function onCancelClick(): Promise<void> {
    if (jobId === null) return;
    cancelledFlag = true;
    try {
      await cancelJob(jobId);
    } catch (err) {
      errorMessage = err instanceof ApiError ? err.message : 'Cancel failed.';
      cancelledFlag = false;
    }
  }

  async function onApplyClick(): Promise<void> {
    if (jobId === null) return;
    applying = true;
    applyError = null;
    try {
      const result = await getJobResult(jobId);
      onApply?.({
        layout: result.layout as Layout | TraceLayout,
        score: result.score,
        diagnostics: result.diagnostics
      });
    } catch (err) {
      applyError = err instanceof ApiError ? err.message : 'Could not fetch result.';
    } finally {
      applying = false;
    }
  }
</script>

{#if jobId !== null}
  <section class="job-progress" data-status={status} aria-label="Solver job progress">
    <div class="track">
      <div class="track-fill" style:width="{Math.max(0, Math.min(100, percent))}%"></div>
    </div>

    <div class="meta">
      <span class="status-chip mono" data-status={status}>
        <span class="chip-dot" aria-hidden="true"></span>
        {status ?? 'queued'}
      </span>
      <span class="phase mono">{phase ?? ''}</span>
      <span class="pct mono">{percent}%</span>

      <span class="actions">
        {#if showCancel}
          <button type="button" class="action" onclick={onCancelClick} disabled={cancelledFlag}>
            {cancelledFlag ? 'Cancelling…' : 'Cancel'}
          </button>
        {/if}
        {#if showApply}
          <button type="button" class="action primary" onclick={onApplyClick} disabled={applying}>
            {applying ? 'Applying…' : 'Apply to draft'}
          </button>
        {/if}
      </span>
    </div>

    {#if errorMessage !== null}
      <p class="message error mono">{errorMessage}</p>
    {/if}
    {#if applyError !== null}
      <p class="message error mono">{applyError}</p>
    {/if}
    {#if finished && !showApply && !showCancel && errorMessage === null}
      <p class="message hint">Job finished. Pick another action.</p>
    {/if}
  </section>
{/if}

<style>
  .job-progress {
    padding: 0 18px 0;
    background: var(--paper-1);
    border-bottom: 1px solid var(--paper-edge);
  }

  .track {
    position: relative;
    height: 2px;
    background: var(--paper-3);
    border-radius: 0;
    overflow: hidden;
  }

  .track-fill {
    height: 100%;
    background: var(--accent-1);
    transition: width 240ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .job-progress[data-status='failed'] .track-fill {
    background: var(--sev-error);
  }
  .job-progress[data-status='cancelled'] .track-fill {
    background: var(--ink-3);
  }
  .job-progress[data-status='succeeded'] .track-fill {
    background: var(--ok);
  }

  .meta {
    display: flex;
    align-items: center;
    gap: var(--sp-3);
    padding: 6px 0;
    font-size: var(--fs-12);
  }

  .status-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 2px 8px;
    border-radius: var(--r-pill);
    border: 1px solid var(--paper-edge);
    background: var(--paper-2);
    color: var(--ink-2);
    font-size: var(--fs-11);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .status-chip[data-status='queued'] {
    color: var(--ink-2);
  }
  .status-chip[data-status='running'] {
    color: var(--accent-1);
    background: var(--accent-soft);
    border-color: var(--accent-line);
  }
  .status-chip[data-status='succeeded'] {
    color: var(--ok);
    background: var(--ok-soft);
    border-color: rgba(42, 110, 63, 0.3);
  }
  .status-chip[data-status='failed'] {
    color: var(--sev-error);
    background: var(--sev-error-soft);
    border-color: var(--sev-error-line);
  }
  .status-chip[data-status='cancelled'] {
    color: var(--ink-3);
    background: var(--paper-2);
    border-color: var(--paper-edge);
  }

  .chip-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: currentColor;
    display: inline-block;
  }

  .phase {
    color: var(--ink-3);
    font-size: var(--fs-11);
  }

  .pct {
    color: var(--ink-2);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }

  .actions {
    margin-left: auto;
    display: inline-flex;
    gap: 6px;
  }

  .action {
    padding: 4px 10px;
    font-size: var(--fs-12);
  }

  .action.primary {
    background: var(--accent-1);
    border-color: var(--accent-1);
    color: #fff;
  }

  .action.primary:hover:not(:disabled) {
    background: var(--accent-3);
    border-color: var(--accent-3);
  }

  .message {
    margin: 0 0 6px;
    font-size: var(--fs-11);
  }

  .message.error {
    color: var(--sev-error);
  }

  .message.hint {
    color: var(--ink-3);
  }
</style>