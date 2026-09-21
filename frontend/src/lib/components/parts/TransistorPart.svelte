<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * TO-92 transistor — black half-moon body with three leads emerging
   * from the flat bottom edge, labeled E/B/C (or as pinMap dictates).
   * The body's curved side faces the breadboard surface.
   */
  type Props = {
    cells: Point2D[]; // 3 lattice cells in pin order (1, 2, 3)
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    label: string;
    value: string | null;
    locked: boolean;
    selected: boolean;
    dragging: boolean;
  };
  let { cells, SCALE, toSvgPx, label, value, locked, selected, dragging }: Props = $props();

  const pins = $derived(cells.map((c) => toSvgPx(c)));
  const minX = $derived(Math.min(...pins.map((p) => p.x)));
  const maxX = $derived(Math.max(...pins.map((p) => p.x)));
  const maxY = $derived(Math.max(...pins.map((p) => p.y)));
  const cx = $derived((minX + maxX) / 2);
  const cy = $derived(maxY - 1.6 * SCALE);
  const widthPx = $derived(maxX - minX);
  // Body sits just above the row of leads, hanging over the top edge.
  const bodyH = $derived(3.0 * SCALE);
  const bodyW = $derived(Math.max(widthPx + 1.0 * SCALE, 5.0 * SCALE));
</script>

<g class="part-transistor" class:locked class:selected class:dragging>
  <!-- Three leads rising up from each pin -->
  {#each pins as p, i (i)}
    <line
      x1={p.x}
      y1={p.y}
      x2={p.x}
      y2={cy - bodyH * 0.15}
      stroke="#9A9384"
      stroke-width={0.35 * SCALE}
      stroke-linecap="round"
    />
  {/each}

  <!-- TO-92 body: rounded rectangle -->
  <rect
    x={cx - bodyW / 2}
    y={cy - bodyH}
    width={bodyW}
    height={bodyH}
    rx={bodyH * 0.45}
    ry={bodyH * 0.45}
    fill={locked ? '#3F3A32' : '#181715'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 * SCALE : 0.18 * SCALE}
  />

  <!-- Reference designator (centered on body) -->
  <text
    x={cx}
    y={cy - bodyH * 0.55}
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.6, bodyH * 0.28)}
    font-weight="600"
    fill="#F5F2EB"
    pointer-events="none"
  >
    {label}
  </text>

  <!-- Value, if present, on a second line -->
  {#if value !== null}
    <text
      x={cx}
      y={cy - bodyH * 0.22}
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size={Math.max(1.0, bodyH * 0.18)}
      fill="#F5F2EB"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-transistor text {
    user-select: none;
  }
</style>