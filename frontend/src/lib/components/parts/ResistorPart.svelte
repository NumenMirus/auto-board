<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Axial resistor — drawn as a beige pill aligned to the lead span.
   * No color bands (those implied a value we can't actually encode), so
   * the body is clean ceramic with ref + value text printed on it.
   *
   * Coordinates: all math runs in mm. The parent wraps this fragment
   * inside <g transform="translate(cx*SCALE) rotate(angleDeg) scale(SCALE)">
   * and we treat 1 SVG unit = 1 mm for sizing primitives.
   */
  type Props = {
    aSvg: Point2D; // SVG-pixel coordinates of pin 1
    bSvg: Point2D; // SVG-pixel coordinates of pin 2
    SCALE: number;
    label: string;
    value: string | null;
    locked: boolean;
    selected: boolean;
    dragging: boolean;
  };
  let { aSvg, bSvg, SCALE, label, value, locked, selected, dragging }: Props = $props();

  // Compute geometry in mm space.
  const dx = $derived(bSvg.x - aSvg.x);
  const dy = $derived(bSvg.y - aSvg.y);
  const lengthMm = $derived(Math.hypot(dx, dy));
  const angleDeg = $derived((Math.atan2(dy, dx) * 180) / Math.PI);

  // Body takes most of the lead-to-lead span; lead stubs on each side.
  const BODY_LEN_MM = $derived(Math.max(3.5, lengthMm - 2.4));
  const BODY_R_MM = $derived(0.85);
</script>

<g
  class="part-resistor"
  class:locked
  class:selected
  class:dragging
  transform={`translate(${(aSvg.x + bSvg.x) / 2} ${(aSvg.y + bSvg.y) / 2}) rotate(${angleDeg}) scale(${SCALE})`}
>
  <!-- Lead stubs: leave the pin holes visible underneath. -->
  <line
    x1={-lengthMm / 2}
    x2={-BODY_LEN_MM / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width={0.35}
    stroke-linecap="round"
  />
  <line
    x1={BODY_LEN_MM / 2}
    x2={lengthMm / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width={0.35}
    stroke-linecap="round"
  />

  <!-- Ceramic body (axial pill) -->
  <rect
    x={-BODY_LEN_MM / 2}
    y={-BODY_R_MM}
    width={BODY_LEN_MM}
    height={BODY_R_MM * 2}
    rx={BODY_R_MM}
    ry={BODY_R_MM}
    fill={locked ? '#D8D2C2' : '#C9BC95'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#7E6A3C'}
    stroke-width={selected ? 0.6 : 0.18}
  />

  <!-- Reference designator on the left half -->
  <text
    x={-BODY_LEN_MM * 0.18}
    y={-0.05}
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.2, Math.min(2.4, BODY_LEN_MM * 0.18))}
    font-weight="500"
    fill="#3A2F12"
    pointer-events="none"
  >
    {label}
  </text>

  <!-- Value text on the right half -->
  {#if value !== null}
    <text
      x={BODY_LEN_MM * 0.22}
      y={-0.05}
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size={Math.max(1.0, Math.min(2.0, BODY_LEN_MM * 0.16))}
      fill="#3A2F12"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-resistor text {
    user-select: none;
  }
</style>