<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Pin header strip (HEADER-1xN) — black plastic block with N square
   * pads visible on the face. Pins are evenly spaced along a row.
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

  const padX = $derived(1.2 * SCALE);
  const padY = $derived(1.5 * SCALE);
  const bodyX = $derived(minX - padX);
  const bodyY = $derived(minY - padY);
  const bodyW = $derived(maxX - minX + padX * 2);
  const bodyH = $derived(maxY - minY + padY * 2);
  const cx = $derived((minX + maxX) / 2);
  const pinCount = $derived(cells.length);

  // Square pads visible on the face. Spaced evenly across the body width.
  const padSize = $derived(Math.min(1.2 * SCALE, bodyW / (pinCount + 1) * 0.65));
  const padStepX = $derived(pinCount > 1 ? (bodyW - 2 * 0.4 * SCALE) / (pinCount - 1) : 0);
  const padStartX = $derived(cx - (padStepX * (pinCount - 1)) / 2);
</script>

<g class="part-header" class:locked class:selected class:dragging>
  <rect
    x={bodyX}
    y={bodyY}
    width={bodyW}
    height={bodyH}
    rx={0.5 * SCALE}
    ry={0.5 * SCALE}
    fill={locked ? '#D8D2C2' : '#181715'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 * SCALE : 0.18 * SCALE}
  />

  {#each Array(pinCount) as _, i (i)}
    <rect
      x={padStartX + i * padStepX - padSize / 2}
      y={(minY + maxY) / 2 - padSize / 2}
      width={padSize}
      height={padSize}
      fill="#F5F2EB"
      opacity={dragging ? 0.45 : 1}
    />
  {/each}

  <!-- Reference designator below the body -->
  <text
    x={cx}
    y={bodyY + bodyH + 0.6 * SCALE}
    text-anchor="middle"
    dominant-baseline="hanging"
    font-family="'JetBrains Mono', monospace"
    font-size={Math.max(1.3, Math.min(bodyW, bodyH) * 0.24)}
    font-weight="600"
    fill="#F5F2EB"
    pointer-events="none"
  >
    {label}
  </text>
</g>

<style>
  .part-header text {
    user-select: none;
  }
</style>