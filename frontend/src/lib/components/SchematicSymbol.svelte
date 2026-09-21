<script lang="ts">
  import type { SymbolShape } from '../schematic/catalog';
  import { terminalOffsets, symbolBox } from '../schematic/geometry';
  import { SYMBOLS } from '../schematic/symbols';

  type Props = {
    shape: SymbolShape;
    pins: string[];
    label?: string | null;
    value?: string | null;
    selected?: boolean;
    showPinNames?: boolean;
  };
  let {
    shape,
    pins,
    label = null,
    value = null,
    selected = false,
    showPinNames = true
  }: Props = $props();

  // The body geometry is the single source of truth — terminalOffsets()
  // and symbolBox() from lib/schematic/geometry.ts own the layout math so
  // this component never duplicates the offset rules.
  const offsets = $derived(terminalOffsets(shape, pins));
  const box = $derived(symbolBox(shape, pins));

  // Pre-compute common body geometry once. Pins list is small (≤28 for DIP-28)
  // so a derived recompute on every pin change is cheap.
  const halfCount = $derived(
    shape === 'ic' ? Math.max(0, Math.floor(pins.length / 2)) : 0
  );

  // Known-shape guard: TS narrows the union but the catalog can widen, and
  // a runtime footprint could carry an empty `pins` array. Anything outside
  // the ten palette shapes falls back to a dashed outline with all stubs
  // down the left side.
  const KNOWN_SHAPES: ReadonlySet<SymbolShape> = new Set([
    'resistor',
    'capacitor',
    'capacitor-polar',
    'diode',
    'led',
    'transistor',
    'ic',
    'switch',
    'header',
    'connector'
  ]);
  const isKnownShape = $derived(KNOWN_SHAPES.has(shape));
  const isFallback = $derived(!isKnownShape || (shape === 'ic' && pins.length === 0));

  // Stroke colors switch on selection. Body fill stays paper-0 always;
  // the halo rect (only rendered when selected) carries the accent glow.
  const strokeColor = $derived(selected ? 'var(--accent-1)' : 'var(--ink-1)');

  // Font size note: SVG `font-size` resolves literal SVG units, not CSS
  // custom properties, across every browser we ship to. We pass a number
  // directly here (1.6 grid units ≈ readable at the 10× sheet scale) and
  // rely on `font-family` for the type system — `font-family` DOES resolve
  // var(--font-mono) because CSS variables apply via the inherited style
  // chain; only length-valued SVG presentation attributes are locked to
  // literal numbers.
  const LABEL_FONT_SIZE = 1.6;
  const PIN_FONT_SIZE = 1.2;

  // Anchor for label/value text — label sits ABOVE the bounding box,
  // value sits BELOW. Both share the box's horizontal mid-line so a
  // rotated node carries all three together under the parent's transform.
  const labelY = $derived(-0.6);
  const valueY = $derived(box.h + 1.4);

  function pinNumber(p: string): number {
    const n = Number(p);
    return Number.isFinite(n) ? n : 0;
  }

  // Sort pins the same way as the catalog (numeric ascending) so a
  // generated DIP-N walks left-side then right-side in pin order.
  const sortedPins = $derived([...pins].sort((a, b) => pinNumber(a) - pinNumber(b)));

  // Whether the offset table matches the pins list — used to decide if we
  // can render per-pin name labels. If terminalOffsets returns nothing
  // usable we skip rather than crashing.
  const canShowPinNames = $derived(
    showPinNames && offsets !== undefined && Object.keys(offsets).length === pins.length
  );
</script>

<!--
  This file is intentionally a fragment (no <svg> root) — the parent
  supplies the outer <svg> and a wrapping <g transform="translate(x*S)
  rotate(rotation) scale(S)">. 1 grid unit here = 1 SVG unit; the parent
  multiplies by SCHEMATIC_SCALE (10). Do not bake the scale into this file.
-->

{#if isFallback}
  <!-- Unknown shape / empty pins: dashed rectangle plus all stubs on the
       left side. Never crash, never render nothing. -->
  <g class="schematic-symbol schematic-symbol-fallback">
    {#if selected}
      <rect
        class="halo"
        x={-0.4}
        y={-0.4}
        width={box.w + 0.8}
        height={box.h + 0.8}
        fill="var(--accent-glow)"
        fill-opacity="0.5"
        stroke="none"
      />
    {/if}
    <rect
      x={0}
      y={0}
      width={box.w}
      height={box.h}
      fill="var(--paper-0)"
      stroke={strokeColor}
      stroke-width="0.3"
      stroke-dasharray="1 1"
    />
    {#each sortedPins as pin, i (pin)}
      <line
        x1={-1}
        y1={i + 0.5}
        x2={0}
        y2={i + 0.5}
        stroke="var(--ink-1)"
        stroke-width="0.3"
      />
    {/each}
    {#if canShowPinNames}
      {#each sortedPins as pin, i (pin)}
        <text
          x={-1.1}
          y={i + 0.5 + 0.35}
          text-anchor="end"
          font-size={PIN_FONT_SIZE}
          font-family="var(--font-mono)"
          fill="var(--ink-3)"
          stroke="none"
        >{pin}</text>
      {/each}
    {/if}
  </g>
{:else}
  <g class="schematic-symbol" class:selected>
    {#if selected}
      <rect
        class="halo"
        x={-0.4}
        y={-0.4}
        width={box.w + 0.8}
        height={box.h + 0.8}
        fill="var(--accent-glow)"
        fill-opacity="0.5"
        stroke="none"
      />
    {/if}

    {#if shape === 'ic'}
      {@const Body = SYMBOLS[shape]}
      <Body {strokeColor} {halfCount} />
    {:else if shape === 'header' || shape === 'connector'}
      {@const Body = SYMBOLS[shape]}
      <Body {strokeColor} pins={pins.length} />
    {:else if SYMBOLS[shape]}
      {@const Body = SYMBOLS[shape]}
      <Body {strokeColor} />
    {/if}

    {#if canShowPinNames}
      {#each sortedPins as pin (pin)}
        {@const off = offsets[pin]}
        {#if off}
          <text
            x={off.x + 0.2}
            y={off.y + 0.35}
            font-size={PIN_FONT_SIZE}
            font-family="var(--font-mono)"
            fill="var(--ink-3)"
            stroke="none"
          >{pin}</text>
        {/if}
      {/each}
    {/if}

    {#if label !== null}
      <text
        class="schematic-symbol-label"
        x={box.w / 2}
        y={labelY}
        text-anchor="middle"
        font-size={LABEL_FONT_SIZE}
        font-family="var(--font-mono)"
        fill="var(--ink-2)"
        stroke="none"
      >{label}</text>
    {/if}

    {#if value !== null}
      <text
        class="schematic-symbol-value"
        x={box.w / 2}
        y={valueY}
        text-anchor="middle"
        font-size={LABEL_FONT_SIZE}
        font-family="var(--font-mono)"
        fill="var(--ink-3)"
        stroke="none"
      >{value}</text>
    {/if}
  </g>
{/if}

<style>
  .schematic-symbol {
    shape-rendering: geometricPrecision;
  }
  .schematic-symbol text {
    user-select: none;
  }
</style>