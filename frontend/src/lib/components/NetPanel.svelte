<script lang="ts">
  import type { Net, NetClass } from '$lib/types';

  type Props = {
    nets: Net[];
    selectedNetId?: string | null;
    onSelectNet?: ((netId: string | null) => void) | undefined;
    onChangeNetClass?: ((netId: string, netClass: NetClass) => void) | undefined;
    onChangePriority?: ((netId: string, priority: number) => void) | undefined;
  };
  let {
    nets,
    selectedNetId = null,
    onSelectNet = undefined,
    onChangeNetClass = undefined,
    onChangePriority = undefined
  }: Props = $props();

  const NET_CLASSES: NetClass[] = [
    'ground',
    'power',
    'high-current',
    'analog-sensitive',
    'clock',
    'switching',
    'digital',
    'low-priority',
    'custom'
  ];

  // Wire color comes from the net class — ground is dark, power is
  // regulated red, everything else is the spec's blue palette. We expose
  // the actual hex so the user can tell at a glance which jumper belongs
  // to which net.
  function classSwatch(cls: NetClass): string {
    switch (cls) {
      case 'ground':
        return 'var(--wire-gnd)';
      case 'power':
        return 'var(--wire-vcc)';
      case 'high-current':
        return '#C2820F';
      case 'analog-sensitive':
        return '#7B3FA8';
      case 'clock':
        return '#0E7C8C';
      case 'switching':
        return '#D6332B';
      case 'digital':
        return '#1F77B4';
      case 'low-priority':
        return '#9A9384';
      case 'custom':
        return '#4F4F4F';
    }
  }

  function classLabel(cls: NetClass): string {
    switch (cls) {
      case 'analog-sensitive':
        return 'analog';
      case 'high-current':
        return 'hi-current';
      case 'low-priority':
        return 'low-prio';
      default:
        return cls;
    }
  }
</script>

<section class="net-panel" aria-label="Nets">
  {#if nets.length === 0}
    <p class="empty">No nets</p>
  {:else}
    <ul>
      {#each nets as net (net.id)}
        {@const isSelected = selectedNetId === net.id}
        <li class="net-row" class:selected={isSelected}>
          <button
            type="button"
            class="net-button"
            onclick={() => onSelectNet?.(selectedNetId === net.id ? null : net.id)}
            aria-pressed={isSelected}
            title={`Highlight ${net.name} on the board`}
          >
            <span class="swatch" style:background={classSwatch(net.netClass)} aria-hidden="true"></span>
            <span class="net-name">{net.name}</span>
            <span class="net-meta mono">
              {net.pins.length} pin{net.pins.length === 1 ? '' : 's'}
            </span>
          </button>
          <div class="net-controls">
            <label class="cls-control">
              <span class="sr-only">Class</span>
              <span class="cls-swatch" style:background={classSwatch(net.netClass)} aria-hidden="true"></span>
              <select
                value={net.netClass}
                onchange={(e) => {
                  const v = (e.currentTarget as HTMLSelectElement).value as NetClass;
                  onChangeNetClass?.(net.id, v);
                }}
                onclick={(e) => e.stopPropagation()}
                aria-label={`Class for ${net.name}`}
              >
                {#each NET_CLASSES as cls (cls)}
                  <option value={cls}>{classLabel(cls)}</option>
                {/each}
              </select>
            </label>
            <label class="pri-control">
              <span class="sr-only">Priority</span>
              <input
                type="number"
                value={net.priority}
                oninput={(e) => {
                  const v = Number((e.currentTarget as HTMLInputElement).value);
                  if (Number.isFinite(v)) onChangePriority?.(net.id, v);
                }}
                onclick={(e) => e.stopPropagation()}
                step="1"
                min="0"
                aria-label={`Priority for ${net.name}`}
              />
            </label>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .net-panel {
    font-size: var(--fs-12);
  }

  .empty {
    color: var(--ink-3);
    font-style: italic;
    padding: var(--sp-3);
    margin: 0;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .net-row {
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid var(--paper-edge);
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .net-row:last-child {
    border-bottom: none;
  }

  .net-row.selected {
    background: var(--accent-soft);
  }

  .net-row.selected .net-name {
    color: var(--accent-1);
  }

  .net-button {
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    background: transparent;
    border: none;
    padding: 8px 12px;
    text-align: left;
    cursor: pointer;
    color: inherit;
    transition: background-color 120ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .net-button:hover {
    background: var(--paper-2);
  }

  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    box-shadow: inset 0 0 0 1px rgba(24, 23, 21, 0.18);
  }

  .net-name {
    font-weight: 500;
    color: var(--ink-1);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .net-meta {
    color: var(--ink-3);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .net-controls {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 0 8px 0 0;
  }

  .cls-control,
  .pri-control {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .cls-swatch {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(24, 23, 21, 0.18);
  }

  .net-controls select,
  .net-controls input {
    padding: 2px 4px;
    font-size: 11px;
    border: 1px solid var(--paper-edge);
    border-radius: 3px;
    background: var(--paper-0);
    color: var(--ink-1);
    min-width: 0;
  }

  .net-controls select:focus,
  .net-controls input:focus {
    outline: none;
    border-color: var(--accent-1);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .net-controls select {
    width: 86px;
  }

  .net-controls input {
    width: 48px;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    border: 0;
  }
</style>