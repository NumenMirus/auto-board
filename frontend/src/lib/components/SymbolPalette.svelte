<script lang="ts">
  import type { SchematicPortKind } from '$lib/types';
  import {
    PALETTE,
    PORT_PALETTE,
    type PaletteEntry,
    type PaletteGroup
  } from '../schematic/catalog';
  import { symbolBox } from '../schematic/geometry';
  import SchematicSymbol from './SchematicSymbol.svelte';

  type Props = {
    armedFootprintId?: string | null;
    armedPortKind?: SchematicPortKind | null;
    onArmSymbol?: ((footprintId: string) => void) | undefined;
    onArmPort?: ((portKind: SchematicPortKind) => void) | undefined;
  };
  let {
    armedFootprintId = null,
    armedPortKind = null,
    onArmSymbol = undefined,
    onArmPort = undefined
  }: Props = $props();

  const SYMBOL_GROUPS: PaletteGroup[] = [
    'Passives',
    'Semiconductors',
    'ICs',
    'Switches',
    'Connectors'
  ];

  /** Representative pin count for a shape, used to size the palette preview. */
  function previewPinsFor(shape: PaletteEntry['shape']): string[] {
    switch (shape) {
      case 'resistor':
      case 'capacitor':
      case 'capacitor-polar':
      case 'diode':
      case 'led':
        return ['1', '2'];
      case 'transistor':
        return ['1', '2', '3'];
      case 'switch':
        return ['1', '2', '3', '4'];
      case 'ic':
      case 'header':
      case 'connector':
        return Array.from({ length: 8 }, (_, i) => String(i + 1));
    }
  }

  const grouped = $derived.by(() => {
    const out: Array<{ group: PaletteGroup; entries: PaletteEntry[] }> = [];
    for (const group of SYMBOL_GROUPS) {
      const entries = PALETTE.filter((entry) => entry.group === group);
      if (entries.length > 0) {
        out.push({ group, entries });
      }
    }
    return out;
  });

  function previewTransform(shape: PaletteEntry['shape'], pins: readonly string[]): string {
    const box = symbolBox(shape, pins);
    return `translate(${-box.w / 2}, ${-box.h / 2})`;
  }

  /** Fixed thumbnail box for every palette preview. Uniform rows keep the list
   *  scannable; the viewBox still spans the full symbol, so the SVG default
   *  `preserveAspectRatio="xMidYMid meet"` scales each symbol down to fit. */
  const PREVIEW_W = 40;
  const PREVIEW_H = 26;

  function previewView(shape: PaletteEntry['shape'], pins: readonly string[]): {
    w: number;
    h: number;
    viewBox: string;
  } {
    const box = symbolBox(shape, pins);
    const padX = 1;
    const padY = 1;
    return {
      w: PREVIEW_W,
      h: PREVIEW_H,
      viewBox: `${-padX} ${-padY} ${box.w + padX * 2} ${box.h + padY * 2}`
    };
  }
</script>

<section class="palette" aria-label="Component palette">
  {#each grouped as section (section.group)}
    <div class="group">
      <h3>{section.group}</h3>
      <ul>
        {#each section.entries as entry (entry.footprintId)}
          {@const pins = previewPinsFor(entry.shape)}
          {@const prev = previewView(entry.shape, pins)}
          {@const isArmed = armedFootprintId === entry.footprintId}
          <li>
            <button
              type="button"
              class="row"
              class:armed={isArmed}
              aria-pressed={isArmed}
              draggable="true"
              ondragstart={(e) => {
                if (e.dataTransfer) {
                  e.dataTransfer.setData('application/x-autoboard-symbol', entry.footprintId);
                  e.dataTransfer.effectAllowed = 'copy';
                }
              }}
              onclick={() => onArmSymbol?.(entry.footprintId)}
              title={`Drag ${entry.label} onto the schematic`}
            >
              <svg
                width={prev.w}
                height={prev.h}
                viewBox={prev.viewBox}
                aria-hidden="true"
                focusable="false"
              >
                <g transform={previewTransform(entry.shape, pins)}>
                  <SchematicSymbol shape={entry.shape} {pins} showPinNames={false} />
                </g>
              </svg>
              <span class="label">{entry.label}</span>
              <span class="fp-id mono">{entry.footprintId}</span>
            </button>
          </li>
        {/each}
      </ul>
    </div>
  {/each}

  <div class="group group-power">
    <h3>Power</h3>
    <ul>
      {#each PORT_PALETTE as entry (entry.portKind)}
        {@const isArmed = armedPortKind === entry.portKind}
        <li>
          <button
            type="button"
            class="row port-row"
            class:armed={isArmed}
            aria-pressed={isArmed}
            draggable="true"
            ondragstart={(e) => {
              if (e.dataTransfer) {
                e.dataTransfer.setData('application/x-autoboard-port', entry.portKind);
                e.dataTransfer.effectAllowed = 'copy';
              }
            }}
            onclick={() => onArmPort?.(entry.portKind)}
            title={`Drag ${entry.label} onto the schematic`}
          >
            <svg width={PREVIEW_W} height={PREVIEW_H} viewBox="0 0 6 5" aria-hidden="true" focusable="false">
              {#if entry.portKind === 'ground'}
                <!-- matches the canvas port: terminal at top, glyph drawn below -->
                <line x1="3" y1="0" x2="3" y2="2" stroke="var(--wire-gnd)" stroke-width="0.18" />
                <polygon points="-0.2,2 6.2,2 3,4" fill="var(--wire-gnd)" opacity="0.1" stroke="none" />
                <line x1="-0.2" y1="2" x2="6.2" y2="2" stroke="var(--wire-gnd)" stroke-width="0.28" stroke-linecap="round" />
                <line x1="0.8" y1="2.7" x2="5.2" y2="2.7" stroke="var(--wire-gnd)" stroke-width="0.24" stroke-linecap="round" />
                <line x1="1.8" y1="3.4" x2="4.2" y2="3.4" stroke="var(--wire-gnd)" stroke-width="0.2" stroke-linecap="round" />
              {:else if entry.portKind === 'power'}
                <!-- matches the canvas port: terminal at bottom, glyph drawn above -->
                <line x1="3" y1="5" x2="3" y2="3" stroke="var(--wire-vcc)" stroke-width="0.18" />
                <line x1="-0.2" y1="3" x2="6.2" y2="3" stroke="var(--wire-vcc)" stroke-width="0.26" stroke-linecap="round" />
                <circle cx="3" cy="1.6" r="1.1" fill="var(--paper-1)" stroke="var(--wire-vcc)" stroke-width="0.2" />
                <line x1="2.4" y1="1.6" x2="3.6" y2="1.6" stroke="var(--wire-vcc)" stroke-width="0.18" stroke-linecap="round" />
                <line x1="3" y1="1" x2="3" y2="2.2" stroke="var(--wire-vcc)" stroke-width="0.18" stroke-linecap="round" />
                <text
                  x="3"
                  y="-0.1"
                  text-anchor="middle"
                  font-family="var(--font-mono)"
                  font-size="0.8"
                  font-weight="600"
                  fill="var(--wire-vcc)"
                >{entry.defaultNetName}</text>
              {:else}
                <line x1="0.5" y1="2" x2="1.6" y2="2" stroke="var(--ink-1)" stroke-width="0.18" />
                <rect x="1.6" y="1" width="3.4" height="2" fill="none" stroke="var(--ink-1)" stroke-width="0.18" rx="0.2" />
                <line x1="2" y1="1" x2="2" y2="3" stroke="var(--ink-1)" stroke-width="0.14" />
              {/if}
            </svg>
            <span class="label">{entry.label}</span>
            <span class="fp-id mono">{entry.defaultNetName}</span>
          </button>
        </li>
      {/each}
    </ul>
  </div>
</section>

<style>
  .palette {
    display: flex;
    flex-direction: column;
    gap: var(--sp-4);
    padding: var(--sp-3);
    background: var(--paper-2);
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }

  .group h3 {
    margin: 0 0 var(--sp-1) 0;
    padding: 0 var(--sp-1);
    color: var(--ink-3);
    font-size: var(--fs-11);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
  }

  li {
    margin: 0;
  }

  .row {
    width: 100%;
    display: grid;
    grid-template-columns: 40px 1fr auto;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2) var(--sp-3);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-2);
    color: var(--ink-1);
    text-align: left;
    font: inherit;
    cursor: grab;
    transition:
      background-color var(--dur-fast) var(--ease-out),
      border-color var(--dur-fast) var(--ease-out),
      color var(--dur-fast) var(--ease-out);
  }

  .row:hover {
    background: var(--paper-3);
  }

  .row:active {
    cursor: grabbing;
  }

  .row.armed {
    background: var(--accent-soft);
    border-color: var(--accent-line);
    color: var(--accent-1);
  }

  .row.armed .fp-id {
    color: var(--accent-1);
  }

  .row svg {
    display: block;
    flex-shrink: 0;
  }

  .label {
    font-size: var(--fs-13);
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fp-id {
    font-size: var(--fs-11);
    color: var(--ink-4);
    font-family: var(--font-mono);
  }

  .group-power .row {
    cursor: grab;
  }
</style>
