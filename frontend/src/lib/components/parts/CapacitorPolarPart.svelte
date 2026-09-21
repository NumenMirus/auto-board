<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Polarized electrolytic capacitor — black cylindrical body lying
   * between the leads, with a vertical silver stripe (the "-" marker)
   * and a longer lead on the "+" side. Pin 1 is conventionally positive.
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

  const BODY_LEN_MM = $derived(Math.max(4.0, leadLen - 2.4));
  const BODY_R_MM = 1.6;
  // The "+" lead (pin 1) is rendered slightly longer than the "-" lead,
  // matching a real through-hole electrolytic cap.
  const PLUS_OFFSET_MM = 0.6;
</script>

<g
  class="part-capacitor-polar"
  class:locked
  class:selected
  class:dragging
  transform={`translate(${(aSvg.x + bSvg.x) / 2} ${(aSvg.y + bSvg.y) / 2}) rotate(${angleDeg}) scale(${SCALE})`}
>
  <!-- Lead stubs: pin 1 (left) is the + lead, slightly longer. -->
  <line
    x1={-leadLen / 2}
    x2={-BODY_LEN_MM / 2}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />
  <line
    x1={BODY_LEN_MM / 2}
    x2={leadLen / 2 + PLUS_OFFSET_MM}
    y1="0"
    y2="0"
    stroke="#9A9384"
    stroke-width="0.35"
    stroke-linecap="round"
  />

  <!-- Cylindrical body: rounded rectangle aligned with the lead axis -->
  <rect
    x={-BODY_LEN_MM / 2}
    y={-BODY_R_MM}
    width={BODY_LEN_MM}
    height={BODY_R_MM * 2}
    rx={BODY_R_MM}
    ry={BODY_R_MM}
    fill={locked ? '#3F3A32' : '#181715'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 : 0.15}
  />

  <!-- Cathode stripe (negative side) -->
  <rect
    x={-BODY_LEN_MM / 2 + 0.35}
    y={-BODY_R_MM + 0.15}
    width={BODY_LEN_MM * 0.18}
    height={BODY_R_MM * 2 - 0.3}
    fill="#D6D2C4"
    opacity={dragging ? 0.35 : 0.85}
  />
  <text
    x={-BODY_LEN_MM / 2 + 0.55 + BODY_LEN_MM * 0.09}
    y="0"
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size="1.1"
    font-weight="700"
    fill="#181715"
    pointer-events="none"
  >
    −
  </text>

  <!-- Top hat (cap top) suggestion -->
  <ellipse
    cx={BODY_LEN_MM / 2}
    cy="0"
    rx="0.35"
    ry={BODY_R_MM - 0.05}
    fill="#3F3A32"
    stroke="none"
    opacity={dragging ? 0.4 : 0.7}
  />

  <!-- Reference and value -->
  <text
    x={BODY_LEN_MM * 0.05}
    y={-0.05}
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.1, Math.min(2.0, BODY_LEN_MM * 0.18))}
    font-weight="600"
    fill="#F5F2EB"
    pointer-events="none"
  >
    {label}
  </text>
  {#if value !== null}
    <text
      x={BODY_LEN_MM * 0.32}
      y={-0.05}
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size={Math.max(0.9, Math.min(1.6, BODY_LEN_MM * 0.14))}
      fill="#F5F2EB"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-capacitor-polar text {
    user-select: none;
  }
</style>