<script lang="ts">
  import type { Diagnostic, DiagnosticSeverity } from '$lib/types';

  type Props = {
    diagnostics: Diagnostic[];
    onSelect?: ((d: Diagnostic) => void) | undefined;
    // True once the validator has run at least once. Lets the empty
    // state distinguish "nothing to show yet" from "we ran the validator
    // and the layout is clean".
    validated?: boolean;
  };
  let { diagnostics, onSelect = undefined, validated = false }: Props = $props();

  // Stable grouping order — the spec locks severity hierarchy (error first,
  // warning second, info last). Inside a group the backend's id is already
  // stable across runs so a plain sort by id gives a stable order.
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
</script>

<section class="diagnostics-panel" aria-label="Diagnostics">
  {#if diagnostics.length === 0}
    {#if validated}
      <p class="empty-valid">Layout is valid</p>
    {:else}
      <p class="empty-idle">No diagnostics</p>
    {/if}
  {:else}
    {#each SEVERITY_ORDER as sev (sev)}
      {#if grouped[sev].length > 0}
        <div class={`bucket bucket-${sev}`}>
          <header class="bucket-header">
            <span class="bucket-label">{sev}</span>
            <span class="bucket-count">{grouped[sev].length}</span>
          </header>
          <ul>
            {#each grouped[sev] as d (d.id)}
              <li>
                <button type="button" class="row" onclick={() => onSelect?.(d)}>
                  <code class="code">{d.code}</code>
                  <span class="message">{d.message}</span>
                  {#if d.suggestion !== null}
                    <span class="suggestion">→ {d.suggestion}</span>
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
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    font-size: 13px;
  }

  .empty-valid {
    margin: 0;
    padding: var(--space-2);
    color: var(--color-info);
    background: rgba(37, 99, 235, 0.08);
    border-left: 3px solid var(--color-info);
    border-radius: var(--radius-sm);
    font-style: italic;
  }

  .empty-idle {
    margin: 0;
    padding: var(--space-2);
    color: var(--color-muted);
    background: transparent;
    border-left: 3px solid var(--color-border);
    border-radius: var(--radius-sm);
    font-style: italic;
  }

  .bucket {
    border-radius: var(--radius-sm);
    overflow: hidden;
  }

  .bucket-error {
    border-left: 3px solid var(--color-error);
  }
  .bucket-warning {
    border-left: 3px solid var(--color-warning);
  }
  .bucket-info {
    border-left: 3px solid var(--color-info);
  }

  .bucket-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: var(--space-1) var(--space-2);
    background: var(--color-surface);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.04em;
  }

  .bucket-count {
    color: var(--color-muted);
    font-variant-numeric: tabular-nums;
  }

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  .row {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: var(--space-2);
    background: transparent;
    border: none;
    border-bottom: 1px solid var(--color-border);
    color: inherit;
    text-align: left;
    cursor: pointer;
  }

  .row:hover {
    background: var(--color-surface);
  }

  .code {
    font-size: 11px;
    color: var(--color-muted);
  }

  .message {
    font-size: 13px;
  }

  .suggestion {
    font-size: 12px;
    color: var(--color-muted);
  }
</style>