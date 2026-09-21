<script lang="ts">
  import type { AnyBoardModel, Hole } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    board: AnyBoardModel;
    showLabels: boolean;
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    labelColumns: number[];
    labelRows: string[];
    holeAtGrid: (col: number, row: string) => Hole | undefined;
    jumperToolActive?: boolean;
    highlightHoleId?: string | null;
  };
  let {
    board,
    showLabels,
    SCALE,
    toSvgPx,
    labelColumns,
    labelRows,
    holeAtGrid,
    jumperToolActive = false,
    highlightHoleId = null
  }: Props = $props();

  // Hole drawing. The outer ring defines the pad, the inner dot gives a hint
  // of recess without dominating. Both are kept low-contrast so the grid
  // recedes behind the components and traces.
  const HOLE_RADIUS_MM = 0.6;
  const HOLE_INNER_MM = 0.32;
</script>

<g class="holes">
  {#each board.holes as hole (hole.id)}
    {#if hole.enabled}
      {@const svgPt = toSvgPx({ x: hole.point.x, y: hole.point.y })}
      {@const r = HOLE_RADIUS_MM * SCALE}
      {@const ir = HOLE_INNER_MM * SCALE}
      {@const isHighlight = highlightHoleId === hole.id}
      {@const isPickable = jumperToolActive}
      <g class="hole-group" class:pickable={isPickable}>
        <circle
          class="hole-outer"
          cx={svgPt.x}
          cy={svgPt.y}
          r={r}
          fill="var(--paper-0)"
          stroke={isHighlight ? 'var(--accent-1)' : '#D8D3C5'}
          stroke-width={isHighlight ? 0.5 * SCALE : 0.18 * SCALE}
          data-hole-id={hole.id}
        />
        <circle
          cx={svgPt.x}
          cy={svgPt.y}
          r={ir}
          fill="#B5AE9F"
          pointer-events="none"
        />
      </g>
    {/if}
  {/each}
</g>

{#if jumperToolActive && highlightHoleId !== null}
  {@const start = board.holes.find((h) => h.id === highlightHoleId)}
  {#if start}
    {@const svgPt = toSvgPx({ x: start.point.x, y: start.point.y })}
    <circle
      class="hole-highlight"
      cx={svgPt.x}
      cy={svgPt.y}
      r={HOLE_RADIUS_MM * 2.6 * SCALE}
      fill="none"
      stroke="var(--accent-1)"
      stroke-width={0.8 * SCALE}
      stroke-dasharray={`${0.8 * SCALE} ${0.6 * SCALE}`}
      pointer-events="none"
    />
  {/if}
{/if}

{#if showLabels}
  <g class="labels" aria-hidden="true">
    {#each labelColumns as col (col)}
      {@const h = holeAtGrid(col, labelRows[0])}
      {#if h}
        {@const svgPt = toSvgPx({ x: h.point.x, y: h.point.y })}
        <text
          x={svgPt.x}
          y={svgPt.y - 3.0 * SCALE}
          text-anchor="middle"
          font-family="'JetBrains Mono', monospace"
          font-size="2.0"
          font-weight="400"
          fill="#A8A294"
        >
          {col}
        </text>
      {/if}
    {/each}
    {#each labelRows as row (row)}
      {@const h = holeAtGrid(1, row)}
      {#if h}
        {@const svgPt = toSvgPx({ x: h.point.x, y: h.point.y })}
        <text
          x={svgPt.x - 2.8 * SCALE}
          y={svgPt.y + 1.0 * SCALE}
          text-anchor="end"
          font-family="'JetBrains Mono', monospace"
          font-size="2.0"
          font-weight="400"
          fill="#A8A294"
        >
          {row}
        </text>
      {/if}
    {/each}
  </g>
{/if}

<style>
  .holes {
    shape-rendering: geometricPrecision;
  }

  .hole-outer {
    transition: stroke 120ms cubic-bezier(0.16, 1, 0.3, 1), stroke-width 120ms
      cubic-bezier(0.16, 1, 0.3, 1);
  }

  .hole-group.pickable:hover .hole-outer {
    stroke: var(--accent-1);
    stroke-width: 0.6;
    cursor: crosshair;
  }

  .labels text {
    user-select: none;
    pointer-events: none;
  }
</style>