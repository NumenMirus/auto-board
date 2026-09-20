<script lang="ts">
  type SolverPreset = 'fast' | 'balanced' | 'quality';
  const PRESETS: SolverPreset[] = ['fast', 'balanced', 'quality'];

  type Props = {
    seed: number;
    preset: SolverPreset;
    placementWeights: Record<string, number>;
    routingWeights: Record<string, number>;
    allowCriticalNetClasses: boolean;
    onSeedChange: (seed: number) => void;
    onPresetChange: (preset: SolverPreset) => void;
    onPlacementWeightsChange: (weights: Record<string, number>) => void;
    onRoutingWeightsChange: (weights: Record<string, number>) => void;
    onAllowCriticalChange: (allow: boolean) => void;
  };
  let {
    seed,
    preset,
    placementWeights,
    routingWeights,
    allowCriticalNetClasses,
    onSeedChange,
    onPresetChange,
    onPlacementWeightsChange,
    onRoutingWeightsChange,
    onAllowCriticalChange
  }: Props = $props();

  let weightsOpen = $state(false);
</script>

<section class="advanced-panel">
  <header class="adv-head">
    <div class="title-block">
      <span class="eyebrow">Solver</span>
      <h3>Advanced settings</h3>
    </div>
    <button
      type="button"
      class="expand"
      aria-expanded={weightsOpen}
      onclick={() => (weightsOpen = !weightsOpen)}
      aria-label="Show weight overrides"
    >
      {weightsOpen ? 'Hide weights' : 'Show weights'}
    </button>
  </header>

  <div class="adv-body">
    <div class="row">
      <label for="preset">Preset</label>
      <div class="seg" role="radiogroup" aria-label="Solver preset">
        {#each PRESETS as p (p)}
          <button
            type="button"
            role="radio"
            aria-checked={preset === p}
            class="seg-btn"
            class:active={preset === p}
            onclick={() => onPresetChange(p)}
          >
            {p}
          </button>
        {/each}
      </div>
    </div>

    <div class="row">
      <label for="seed">Seed</label>
      <div class="seed-input">
        <input
          id="seed"
          type="number"
          value={seed}
          oninput={(e) => {
            const v = Number((e.currentTarget as HTMLInputElement).value);
            if (Number.isFinite(v)) onSeedChange(v);
          }}
          step="1"
        />
        <button
          type="button"
          class="dice"
          aria-label="Randomise seed"
          title="Randomise seed"
          onclick={() => onSeedChange(Math.floor(Math.random() * 1_000_000))}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <rect x="2" y="2" width="3" height="3" fill="currentColor" />
            <rect x="7" y="2" width="3" height="3" fill="currentColor" />
            <rect x="2" y="7" width="3" height="3" fill="currentColor" />
            <rect x="7" y="7" width="3" height="3" fill="currentColor" />
          </svg>
        </button>
      </div>
    </div>

    <div class="row check">
      <label for="allow-critical" class="check-label">
        <input
          id="allow-critical"
          type="checkbox"
          checked={allowCriticalNetClasses}
          onchange={(e) => onAllowCriticalChange((e.currentTarget as HTMLInputElement).checked)}
        />
        <span>Route critical classes (clock · switching · analog)</span>
      </label>
    </div>

    {#if weightsOpen}
      <fieldset>
        <legend>Placement weights</legend>
        {#each Object.entries(placementWeights) as [k, v] (k)}
          <div class="weight-row">
            <label for={`pw-${k}`}>{k}</label>
            <input
              id={`pw-${k}`}
              type="number"
              value={v}
              oninput={(e) => {
                const n = Number((e.currentTarget as HTMLInputElement).value);
                if (Number.isFinite(n)) {
                  onPlacementWeightsChange({ ...placementWeights, [k]: n });
                }
              }}
            />
          </div>
        {/each}
      </fieldset>

      <fieldset>
        <legend>Routing weights</legend>
        {#each Object.entries(routingWeights) as [k, v] (k)}
          <div class="weight-row">
            <label for={`rw-${k}`}>{k}</label>
            <input
              id={`rw-${k}`}
              type="number"
              value={v}
              oninput={(e) => {
                const n = Number((e.currentTarget as HTMLInputElement).value);
                if (Number.isFinite(n)) {
                  onRoutingWeightsChange({ ...routingWeights, [k]: n });
                }
              }}
            />
          </div>
        {/each}
      </fieldset>
    {/if}
  </div>
</section>

<style>
  .advanced-panel {
    padding: 0;
    background: transparent;
  }

  .adv-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-3) var(--sp-3) 0;
  }

  .title-block {
    flex: 1;
  }

  .eyebrow {
    display: block;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    margin-bottom: 2px;
  }

  h3 {
    margin: 0;
    font-size: var(--fs-13);
    font-weight: 600;
    color: var(--ink-1);
  }

  .expand {
    font-size: var(--fs-11);
    color: var(--accent-1);
    background: transparent;
    border: none;
    padding: 4px 6px;
    border-radius: var(--r-2);
  }

  .expand:hover:not(:disabled) {
    background: var(--accent-soft);
  }

  .adv-body {
    padding: var(--sp-3);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .row {
    display: grid;
    grid-template-columns: 64px 1fr;
    align-items: center;
    gap: var(--sp-2);
  }

  .row.check {
    display: flex;
    align-items: center;
  }

  .row label {
    color: var(--ink-3);
    font-size: var(--fs-12);
  }

  .check-label {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--ink-2);
    font-size: var(--fs-12);
    cursor: pointer;
    line-height: 1.3;
  }

  .check-label input[type='checkbox'] {
    accent-color: var(--accent-1);
    width: 14px;
    height: 14px;
    margin: 0;
  }

  .seg {
    display: inline-flex;
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    overflow: hidden;
    background: var(--paper-0);
  }

  .seg-btn {
    padding: 4px 10px;
    font-size: var(--fs-12);
    background: transparent;
    border: none;
    color: var(--ink-2);
    border-radius: 0;
  }

  .seg-btn + .seg-btn {
    border-left: 1px solid var(--paper-edge);
  }

  .seg-btn:hover:not(:disabled) {
    background: var(--paper-2);
    border-color: transparent;
  }

  .seg-btn.active {
    background: var(--accent-1);
    color: #fff;
  }

  .seed-input {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .seed-input input {
    width: 110px;
  }

  .dice {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    color: var(--ink-3);
  }

  .dice:hover:not(:disabled) {
    color: var(--accent-1);
    background: var(--paper-2);
  }

  fieldset {
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    padding: var(--sp-2);
    display: flex;
    flex-direction: column;
    gap: 6px;
    background: var(--paper-1);
  }

  legend {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--ink-3);
    padding: 0 6px;
  }

  .weight-row {
    display: grid;
    grid-template-columns: 1fr 70px;
    align-items: center;
    gap: 8px;
  }

  .weight-row label {
    font-size: var(--fs-11);
    color: var(--ink-2);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .weight-row input {
    font-size: var(--fs-12);
    padding: 2px 4px;
  }
</style>