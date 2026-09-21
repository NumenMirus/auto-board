<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Axial diode — dark glass body (slightly shorter than a resistor so
   * a mixed row of passives reads as different shapes), with a single
   * white cathode band on the pin-2 side.
   */
  type Props = {
    aSvg: Point2D;
    bSvg: Point2D;
    SCALE: number;
    label: string;
    value: string | null;
    locked: boolean;
    selected: boolean;
    dragging: boolean;
  };
  let { aSvg, bSvg, SCALE, label, value, locked, selected, dragging }: Props = $props();

  const dx = $derived(bSvg.x - aSvg.x);
  const dy = $derived(bSvg.y - aSvg.y);
  const lengthMm = $derived(Math.hypot(dx, dy));
  const angleDeg = $derived((Math.atan2(dy, dx) * 180) / Math.PI);

  // Body is shorter than a resistor so diodes don't dominate a row.
  // Length nearly equals width so the body reads as almost square
  // (a flat SOD-ish / axial-rectangular package), not a long pill.
  const BODY_LEN_MM = $derived(Math.max(2.6, Math.min(lengthMm - 2.4, 2.6)));
  const BODY_W_MM = 2.4;
  const BODY_R_MM = 0.25;
  // A single, clear white band on the cathode side.
  const BAND_WIDTH_MM = $derived(Math.min(0.5, BODY_LEN_MM * 0.22));
</script>

<g
  class="part-diode"
  class:locked
  class:selected
  class:dragging
  transform={`translate(${(aSvg.x + bSvg.x) / 2} ${(aSvg.y + bSvg.y) / 2}) rotate(${angleDeg}) scale(${SCALE})`}
>
  <!-- Lead stubs -->
  <line
    x1={-lengthMm / 2}
    x2={-BODY_LEN_MM / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />
  <line
    x1={BODY_LEN_MM / 2}
    x2={lengthMm / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />

  <!-- Dark glass body — almost square: length ~= width -->
  <rect
    x={-BODY_LEN_MM / 2}
    y={-BODY_W_MM / 2}
    width={BODY_LEN_MM}
    height={BODY_W_MM}
    rx={BODY_R_MM}
    ry={BODY_R_MM}
    fill={locked ? '#3F3A32' : '#181715'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 : 0.15}
  />

  <!-- Cathode band on pin-2 side: clean white stripe -->
  <rect
    x={BODY_LEN_MM / 2 - BAND_WIDTH_MM - 0.05}
    y={-BODY_W_MM / 2 + 0.05}
    width={BAND_WIDTH_MM}
    height={BODY_W_MM - 0.1}
    fill="#F5F2EB"
    opacity={dragging ? 0.45 : 1}
  />

  <!-- Reference designator -->
  <text
    x={-BODY_LEN_MM * 0.18}
    y="-0.05"
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.0, Math.min(1.8, BODY_LEN_MM * 0.32))}
    font-weight="500"
    fill="#F5F2EB"
    pointer-events="none"
  >
    {label}
  </text>
  {#if value !== null}
    <text
      x={0}
      y={BODY_W_MM / 2 + 0.9}
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size="1.1"
      fill="#34312B"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-diode text {
    user-select: none;
  }
</style>