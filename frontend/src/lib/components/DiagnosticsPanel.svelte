<script lang="ts">
  import type { Diagnostic, DiagnosticSeverity } from '$lib/types';

  type Props = {
    diagnostics: Diagnostic[];
    onSelect?: ((d: Diagnostic) => void) | undefined;
    validated?: boolean;
  };
  let { diagnostics, onSelect = undefined, validated = false }: Props = $props();

  const SEVERITY_ORDER: DiagnosticSeverity[] = ['error', 'warning', 'info'];

  const grouped = $derived.by(() => {
    const buckets: Record<DiagnosticSeverity, Diagnostic[]> = {
      error: [],
      warning: [],
      info: []
    };
    for (const d of diagnostics) {
      buckets[d.severity].push(d);
    }
    for (const sev of SEVERITY_ORDER) {
      buckets[sev].sort((a, b) => a.id.localeCompare(b.id));
    }
    return buckets;
  });

  // Pretty-print a code like SHORT_BETWEEN_NETS into "Short between nets"
  // for headings. The backend code stays untouched in the chip.
  function prettyCode(code: string): string {
    return code
      .split('_')
      .map((w) => (w.length === 0 ? '' : w[0]?.toUpperCase() + w.slice(1).toLowerCase()))
      .join(' ');
  }
</script>

<section class="diagnostics-panel" aria-label="Diagnostics">
  {#if diagnostics.length === 0}
    {#if validated}
      <div class="empty valid">
        <span class="check" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 14 14">
            <path d="M3 7.5 L6 10.5 L11.5 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" />
          </svg>
        </span>
        <span>Topology valid — no shorts, no opens.</span>
      </div>
    {:else}
      <p class="empty idle">No diagnostics — make a change to verify.</p>
    {/if}
  {:else}
    {#each SEVERITY_ORDER as sev (sev)}
      {#if grouped[sev].length > 0}
        <div class={`bucket bucket-${sev}`}>
          <header class="bucket-head">
            <span class="bucket-dot" aria-hidden="true"></span>
            <span class="bucket-label">{sev}</span>
            <span class="bucket-count mono">{grouped[sev].length}</span>
          </header>
          <ul>
            {#each grouped[sev] as d (d.id)}
              <li>
                <button
                  type="button"
                  class="diag-row"
                  onclick={() => onSelect?.(d)}
                  aria-label={`Diagnostic ${d.code}`}
                >
                  <span class="diag-code mono">{d.code}</span>
                  <span class="diag-title">{prettyCode(d.code)}</span>
                  <span class="diag-msg">{d.message}</span>
                  {#if d.suggestion}
                    <span class="diag-suggest">→ {d.suggestion}</span>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
        </div>
      {/if}
    {/each}
  {/if}
</section>

<style>
  .diagnostics-panel {
    padding: 0;
    font-size: var(--fs-12);
  }

  .empty {
    margin: 0;
    color: var(--ink-3);
    padding: var(--sp-3);
    font-size: var(--fs-12);
  }

  .empty.idle {
    font-style: italic;
  }

  .empty.valid {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--ok);
    font-weight: 500;
  }

  .check {
    color: var(--ok);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--ok-soft);
    border: 1px solid rgba(42, 110, 63, 0.3);
  }

  .bucket {
    padding: var(--sp-3);
  }

  .bucket + .bucket {
    border-top: 1px solid var(--paper-edge);
  }

  .bucket-head {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
  }

  .bucket-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  .bucket-error .bucket-dot {
    background: var(--sev-error);
  }
  .bucket-warning .bucket-dot {
    background: var(--sev-warning);
  }
  .bucket-info .bucket-dot {
    background: var(--sev-info);
  }

  .bucket-label {
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.06em;
    font-weight: 600;
    color: var(--ink-2);
  }

  .bucket-count {
    margin-left: auto;
    font-size: var(--fs-11);
    color: var(--ink-3);
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .diag-row {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 2px;
    width: 100%;
    padding: 8px 10px;
    background: var(--paper-1);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    text-align: left;
    cursor: pointer;
    transition: border-color var(--dur) var(--ease-out), background-color var(--dur) var(--ease-out);
  }

  .diag-row:hover {
    border-color: var(--accent-1);
    background: var(--paper-2);
  }

  .diag-code {
    font-size: 10px;
    font-weight: 600;
    color: var(--ink-3);
    letter-spacing: 0.04em;
  }

  .diag-title {
    font-size: var(--fs-13);
    color: var(--ink-1);
    font-weight: 500;
  }

  .diag-msg {
    font-size: var(--fs-12);
    color: var(--ink-2);
  }

  .diag-suggest {
    font-size: var(--fs-11);
    color: var(--ink-3);
    margin-top: 2px;
  }

  .bucket-error .diag-row {
    background: var(--sev-error-soft);
    border-color: var(--sev-error-line);
  }
  .bucket-error .diag-code {
    color: var(--sev-error);
  }
  .bucket-warning .diag-row {
    background: var(--sev-warning-soft);
    border-color: var(--sev-warning-line);
  }
  .bucket-warning .diag-code {
    color: var(--sev-warning);
  }
  .bucket-info .diag-row {
    background: var(--sev-info-soft);
    border-color: var(--sev-info-line);
  }
  .bucket-info .diag-code {
    color: var(--sev-info);
  }
</style>