<script lang="ts">
  import type { LayoutScore } from '$lib/types';

  type Props = {
    score: LayoutScore | null;
  };
  let { score }: Props = $props();

  const lengthMeters = $derived(score === null ? '0.00' : (score.totalJumperLengthMm / 1000).toFixed(2));
  const roundedTotal = $derived(score === null ? '—' : Math.round(score.total).toString());

  // Compact ratio formatter: "18 / 18" → 100 %, "12 / 15" → 80 %
  function pct(done: number, total: number): string {
    if (total === 0) return '—';
    return `${Math.round((done / total) * 100)}%`;
  }
</script>

<section class="metrics-bar" aria-label="Layout metrics">
  {#if score === null}
    <p class="empty mono">no score yet</p>
  {:else}
    <dl>
      <div class="metric">
        <dt>Placed</dt>
        <dd>
          <span class="value">{score.componentsPlaced}</span>
          <span class="value-sep">/</span>
          <span class="value-muted">{score.componentsTotal}</span>
          <span class="value-pct mono">{pct(score.componentsPlaced, score.componentsTotal)}</span>
        </dd>
      </div>

      <div class="metric">
        <dt>Nets complete</dt>
        <dd>
          <span class="value">{score.netsCompleted}</span>
          <span class="value-sep">/</span>
          <span class="value-muted">{score.netsTotal}</span>
          <span class="value-pct mono">{pct(score.netsCompleted, score.netsTotal)}</span>
        </dd>
      </div>

      <div class="metric">
        <dt>Wires</dt>
        <dd>
          <span class="value">{score.jumperCount}</span>
          <span class="value-pct mono">jumpers</span>
        </dd>
      </div>

      <div class="metric">
        <dt>Wire length</dt>
        <dd>
          <span class="value mono">{lengthMeters}</span>
          <span class="value-pct mono">m</span>
        </dd>
      </div>

      <div class="metric">
        <dt>Crossings</dt>
        <dd>
          <span class="value mono">{score.crossings}</span>
          <span class="value-pct mono">visual</span>
        </dd>
      </div>

      <div class="metric">
        <dt>Score</dt>
        <dd>
          <span class="value mono total">{roundedTotal}</span>
          <span class="value-pct mono">total</span>
        </dd>
      </div>

      <div class="metric" class:has-error={score.errorCount > 0}>
        <dt>Errors</dt>
        <dd>
          <span class="value mono">{score.errorCount}</span>
        </dd>
      </div>

      <div class="metric" class:has-warning={score.warningCount > 0}>
        <dt>Warnings</dt>
        <dd>
          <span class="value mono">{score.warningCount}</span>
        </dd>
      </div>
    </dl>
  {/if}
</section>

<style>
  .metrics-bar {
    padding: var(--sp-3);
    background: transparent;
    font-size: var(--fs-12);
  }

  .empty {
    margin: 0;
    color: var(--ink-3);
    font-style: italic;
    font-size: var(--fs-12);
  }

  dl {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px var(--sp-3);
    margin: 0;
  }

  .metric {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 4px 0;
    border-top: 1px dashed var(--paper-edge);
  }

  .metric:first-child,
  .metric:nth-child(2) {
    border-top: none;
    padding-top: 0;
  }

  dt {
    color: var(--ink-3);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  dd {
    margin: 0;
    display: flex;
    align-items: baseline;
    gap: 4px;
    font-variant-numeric: tabular-nums;
  }

  .value {
    color: var(--ink-1);
    font-size: var(--fs-15);
    font-weight: 600;
    line-height: 1;
  }

  .value.total {
    color: var(--accent-1);
  }

  .value-sep {
    color: var(--ink-3);
    font-size: var(--fs-12);
  }

  .value-muted {
    color: var(--ink-3);
    font-size: var(--fs-12);
  }

  .value-pct {
    margin-left: 4px;
    font-size: 10px;
    color: var(--ink-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .metric.has-error .value {
    color: var(--sev-error);
  }
  .metric.has-warning .value {
    color: var(--sev-warning);
  }
</style>