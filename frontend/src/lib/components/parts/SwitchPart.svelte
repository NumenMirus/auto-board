<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Tactile switch (TACT-SW-4P) — square body covering the pin span
   * with a small circular actuator button on top, dashed lines showing
   * the switch action. Pin pairs are bridged internally.
   */
  type Props = {
    cells: Point2D[];
    toSvgPx: (p: Point2D) => Point2D;
    SCALE: number;
    label: string;
    value: string | null;
    locked: boolean;
    selected: boolean;
    dragging: boolean;
  };
  let { cells, toSvgPx, SCALE, label, value, locked, selected, dragging }: Props = $props();

  const pts = $derived(cells.map((c) => toSvgPx(c)));
  const minX = $derived(Math.min(...pts.map((p) => p.x)));
  const maxX = $derived(Math.max(...pts.map((p) => p.x)));
  const minY = $derived(Math.min(...pts.map((p) => p.y)));
  const maxY = $derived(Math.max(...pts.map((p) => p.y)));

  const padX = $derived(1.5 * SCALE);
  const padY = $derived(1.5 * SCALE);
  const bodyX = $derived(minX - padX);
  const bodyY = $derived(minY - padY);
  const bodyW = $derived(maxX - minX + padX * 2);
  const bodyH = $derived(maxY - minY + padY * 2);
  const cx = $derived((minX + maxX) / 2);
  const cy = $derived((minY + maxY) / 2);

  // Actuator (the round button on top of the switch)
  const actuatorR = $derived(Math.min(bodyW, bodyH) * 0.22);
</script>

<g class="part-switch" class:locked class:selected class:dragging>
  <!-- Body: square outline -->
  <rect
    x={bodyX}
    y={bodyY}
    width={bodyW}
    height={bodyH}
    rx={0.6 * SCALE}
    ry={0.6 * SCALE}
    fill={locked ? '#D8D2C2' : '#3F3A32'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 * SCALE : 0.2 * SCALE}
  />

  <!-- Top side contact indicator -->
  <line
    x1={bodyX + bodyW * 0.1}
    x2={bodyX + bodyW * 0.9}
    y1={bodyY + bodyH * 0.18}
    y2={bodyY + bodyH * 0.18}
    stroke="#9A9384"
    stroke-width={0.18 * SCALE}
    stroke-linecap="round"
  />
  <!-- Bottom side contact indicator -->
  <line
    x1={bodyX + bodyW * 0.1}
    x2={bodyX + bodyW * 0.9}
    y1={bodyY + bodyH * 0.82}
    y2={bodyY + bodyH * 0.82}
    stroke="#9A9384"
    stroke-width={0.18 * SCALE}
    stroke-linecap="round"
  />

  <!-- Actuator: round button -->
  <circle
    cx={cx}
    cy={cy}
    r={actuatorR}
    fill={locked ? '#D8D2C2' : '#9A9384'}
    stroke={selected ? 'var(--accent-1)' : '#34312B'}
    stroke-width={selected ? 0.5 * SCALE : 0.15 * SCALE}
  />

  <!-- Reference designator below the actuator -->
  <text
    x={cx}
    y={bodyY + bodyH + 0.6 * SCALE}
    text-anchor="middle"
    dominant-baseline="hanging"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.3, Math.min(bodyW, bodyH) * 0.18)}
    font-weight="600"
    fill="#181715"
    pointer-events="none"
  >
    {label}
  </text>
</g>

<style>
  .part-switch text {
    user-select: none;
  }
</style>