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
</script>

<details class="advanced-panel">
  <summary>Advanced</summary>
  <div class="body">
    <label class="row">
      <span>Seed</span>
      <input
        type="number"
        value={seed}
        oninput={(e) => {
          const v = Number((e.currentTarget as HTMLInputElement).value);
          if (Number.isFinite(v)) onSeedChange(v);
        }}
        step="1"
      />
    </label>
    <label class="row">
      <span>Preset</span>
      <select
        value={preset}
        onchange={(e) => onPresetChange((e.currentTarget as HTMLSelectElement).value as SolverPreset)}
      >
        {#each PRESETS as p (p)}
          <option value={p}>{p}</option>
        {/each}
      </select>
    </label>
    <label class="row checkbox">
      <input
        type="checkbox"
        checked={allowCriticalNetClasses}
        onchange={(e) => onAllowCriticalChange((e.currentTarget as HTMLInputElement).checked)}
      />
      <span>Allow critical net classes</span>
    </label>

    <fieldset>
      <legend>Placement weights</legend>
      {#each Object.entries(placementWeights) as [key, value] (key)}
        <label class="row">
          <span>{key}</span>
          <input
            type="number"
            value={value}
            oninput={(e) => {
              const v = Number((e.currentTarget as HTMLInputElement).value);
              if (Number.isFinite(v)) onPlacementWeightsChange({ ...placementWeights, [key]: v });
            }}
            step="0.1"
          />
        </label>
      {/each}
    </fieldset>

    <fieldset>
      <legend>Routing weights</legend>
      {#each Object.entries(routingWeights) as [key, value] (key)}
        <label class="row">
          <span>{key}</span>
          <input
            type="number"
            value={value}
            oninput={(e) => {
              const v = Number((e.currentTarget as HTMLInputElement).value);
              if (Number.isFinite(v)) onRoutingWeightsChange({ ...routingWeights, [key]: v });
            }}
            step="0.1"
          />
        </label>
      {/each}
    </fieldset>
  </div>
</details>

<style>
  .advanced-panel {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-surface);
    padding: var(--space-2);
  }

  summary {
    cursor: pointer;
    font-weight: 600;
    user-select: none;
  }

  .body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-2);
    font-size: 13px;
  }

  fieldset {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: var(--space-2);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  legend {
    font-weight: 600;
    padding: 0 var(--space-1);
  }

  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--space-2);
  }

  .row.checkbox {
    flex-direction: row;
    gap: var(--space-1);
  }

  .row input,
  .row select {
    max-width: 12em;
    text-align: right;
  }
</style>