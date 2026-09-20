<script lang="ts">
  import type { LayoutScore } from '$lib/types';

  type Props = {
    score: LayoutScore | null;
  };
  let { score }: Props = $props();

  const lengthMeters = $derived(score === null ? '0.00' : (score.totalJumperLengthMm / 1000).toFixed(2));
  const roundedTotal = $derived(score === null ? 0 : Math.round(score.total));
</script>

<section class="metrics-bar" aria-label="Layout metrics">
  {#if score === null}
    <p class="empty">No score yet</p>
  {:else}
    <dl>
      <div>
        <dt>Componenti piazzati</dt>
        <dd>{score.componentsPlaced} / {score.componentsTotal}</dd>
      </div>
      <div>
        <dt>Net completate</dt>
        <dd>{score.netsCompleted} / {score.netsTotal}</dd>
      </div>
      <div>
        <dt>Jumper</dt>
        <dd>{score.jumperCount}</dd>
      </div>
      <div>
        <dt>Lunghezza jumper stimata</dt>
        <dd>{lengthMeters} m</dd>
      </div>
      <div>
        <dt>Crossing visivi</dt>
        <dd>{score.crossings}</dd>
      </div>
      <div>
        <dt>Errori</dt>
        <dd class="errors">{score.errorCount}</dd>
      </div>
      <div>
        <dt>Warning</dt>
        <dd class="warnings">{score.warningCount}</dd>
      </div>
      <div>
        <dt>Score</dt>
        <dd class="total">{roundedTotal}</dd>
      </div>
    </dl>
  {/if}
</section>

<style>
  .metrics-bar {
    padding: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    font-size: 13px;
  }

  .empty {
    margin: 0;
    color: var(--color-muted);
    font-style: italic;
  }

  dl {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-1) var(--space-2);
    margin: 0;
  }

  div {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    padding: 2px 0;
  }

  dt {
    color: var(--color-muted);
  }

  dd {
    margin: 0;
    font-variant-numeric: tabular-nums;
  }

  .errors {
    color: var(--color-error);
    font-weight: 600;
  }

  .warnings {
    color: var(--color-warning);
    font-weight: 600;
  }

  .total {
    color: var(--color-fg);
    font-weight: 700;
  }
</style>