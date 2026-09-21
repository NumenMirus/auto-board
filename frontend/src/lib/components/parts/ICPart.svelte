<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * DIP (Dual Inline Package) IC — black plastic body with a pin-1
   * indicator notch on the top edge. The body's span covers the full
   * extents of the pin row plus a small margin so the body overhangs
   * the pins.
   */
  type Props = {
    cells: Point2D[]; // All occupied lattice cells
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

  // Body extends slightly past the pin rows so it looks like a real DIP.
  const padX = $derived(1.4 * SCALE);
  const padY = $derived(1.0 * SCALE);
  const bodyX = $derived(minX - padX);
  const bodyY = $derived(minY - padY);
  const bodyW = $derived(maxX - minX + padX * 2);
  const bodyH = $derived(maxY - minY + padY * 2);
  const cx = $derived((minX + maxX) / 2);
  const cy = $derived((minY + maxY) / 2);

  // Pin-1 indicator: a small circle near the top-left corner of the body.
  const dotR = $derived(Math.min(bodyW, bodyH) * 0.06);
  const dotX = $derived(bodyX + bodyW * 0.12);
  const dotY = $derived(bodyY + bodyH * 0.18);
</script>

<g class="part-ic" class:locked class:selected class:dragging>
  <!-- Body -->
  <rect
    x={bodyX}
    y={bodyY}
    width={bodyW}
    height={bodyH}
    rx={1.0 * SCALE}
    ry={1.0 * SCALE}
    fill={locked ? '#3F3A32' : '#181715'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 * SCALE : 0.18 * SCALE}
  />

  <!-- Pin-1 dot -->
  <circle
    cx={dotX}
    cy={dotY}
    r={dotR}
    fill="#F5F2EB"
    opacity={dragging ? 0.5 : 1}
  />

  <!-- Reference designator centered on body -->
  <text
    x={cx}
    y={cy - (value !== null ? 0.35 * SCALE : 0)}
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(2.0, Math.min(bodyW, bodyH) * 0.22)}
    font-weight="600"
    fill="#F5F2EB"
    pointer-events="none"
  >
    {label}
  </text>
  {#if value !== null}
    <text
      x={cx}
      y={cy + 0.6 * SCALE}
      text-anchor="middle"
      dominant-baseline="middle"
      font-family="'JetBrains Mono', monospace"
      font-size={Math.max(1.2, Math.min(bodyW, bodyH) * 0.14)}
      fill="#F5F2EB"
      pointer-events="none"
    >
      {value}
    </text>
  {/if}
</g>

<style>
  .part-ic text {
    user-select: none;
  }
</style>