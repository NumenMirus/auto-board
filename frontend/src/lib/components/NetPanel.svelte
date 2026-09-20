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

  // All nine enum values from the wire model. Order matches the Python
  // NetClass enum so changes are diffable across runs.
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
          >
            <span class="net-name">{net.name}</span>
            <span class="net-meta">
              {net.pins.length} pin{net.pins.length === 1 ? '' : 's'}
            </span>
          </button>
          <div class="net-controls">
            <label>
              <span class="visually-hidden">Class</span>
              <select
                value={net.netClass}
                onchange={(e) => {
                  const v = (e.currentTarget as HTMLSelectElement).value as NetClass;
                  onChangeNetClass?.(net.id, v);
                }}
                onclick={(e) => e.stopPropagation()}
              >
                {#each NET_CLASSES as cls (cls)}
                  <option value={cls}>{cls}</option>
                {/each}
              </select>
            </label>
            <label>
              <span class="visually-hidden">Priority</span>
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
    font-size: 13px;
  }

  .empty {
    color: var(--color-muted);
    font-style: italic;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .net-row {
    display: flex;
    align-items: stretch;
    border-bottom: 1px solid var(--color-border);
  }

  .net-row.selected {
    background: rgba(31, 111, 235, 0.08);
  }

  .net-button {
    flex: 1;
    display: flex;
    justify-content: space-between;
    background: transparent;
    border: none;
    padding: var(--space-2);
    text-align: left;
    cursor: pointer;
    color: inherit;
  }

  .net-button:hover {
    background: var(--color-surface);
  }

  .net-name {
    font-weight: 500;
  }

  .net-meta {
    color: var(--color-muted);
    font-size: 11px;
    align-self: center;
  }

  .net-controls {
    display: flex;
    gap: var(--space-1);
    align-items: center;
    padding: 0 var(--space-2);
  }

  .net-controls select,
  .net-controls input {
    font-size: 12px;
    padding: 2px 4px;
  }

  .net-controls input {
    width: 4em;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    border: 0;
  }
</style>