<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Non-polarized ceramic / film capacitor — yellow ochre disc body
   * with two radial leads emerging from the bottom edge.
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
  const leadLen = $derived(Math.hypot(dx, dy));
  const angleDeg = $derived((Math.atan2(dy, dx) * 180) / Math.PI);

  // Center the disc body midway between the leads.
  const BODY_R_MM = 1.9;
  const LEAD_STUB_MM = $derived(Math.max(1.0, leadLen / 2 - BODY_R_MM));
</script>

<g
  class="part-capacitor"
  class:locked
  class:selected
  class:dragging
  transform={`translate(${(aSvg.x + bSvg.x) / 2} ${(aSvg.y + bSvg.y) / 2}) rotate(${angleDeg}) scale(${SCALE})`}
>
  <!-- Lead stubs from each pin toward the body. -->
  <line
    x1={-leadLen / 2}
    x2={-LEAD_STUB_MM}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />
  <line
    x1={LEAD_STUB_MM}
    x2={leadLen / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />

  <!-- Disc body -->
  <circle
    cx="0"
    cy="0"
    r={BODY_R_MM}
    fill={locked ? '#E2DBCB' : '#D6B85A'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#8A6E20'}
    stroke-width={selected ? 0.6 : 0.2}
  />

  <!-- Subtle highlight crescent for the cylindrical illusion -->
  <path
    d="M -1.0 -1.2 Q 0.0 -1.55 1.0 -1.2"
    fill="none"
    stroke="#F0E2A8"
    stroke-width="0.18"
    stroke-linecap="round"
    opacity={dragging ? 0.45 : 1}
  />

  <!-- Ref designator above value, both centered on the disc. -->
  <text
    x="0"
    y="-0.35"
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size="1.6"
    font-weight="600"
    fill="#3A2F12"
    pointer-events="none"
  >
    {label}
  </text>
  {#if value !== null}
    <text
      x="0"
      y="0.85"
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size="1.2"
      fill="#3A2F12"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-capacitor text {
    user-select: none;
  }
</style>