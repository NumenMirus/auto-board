<script lang="ts">
  import type { BreadboardModel, Hole } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    board: BreadboardModel;
    showLabels: boolean;
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    labelColumns: number[];
    labelRows: string[];
    holeAtGrid: (col: number, row: string) => Hole | undefined;
    // When the jumper tool is active the user is in "pick two holes" mode:
    // we route every hole click into a data-attribute the canvas watches,
    // and draw a ring around the start endpoint so they can see what
    // they've already picked.
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

  const HOLE_RADIUS_MM = 0.75; // ~1.5 mm diameter, matches a 0.3" pitch hole
</script>

<g class="holes">
  {#each board.holes as hole (hole.id)}
    {#if hole.enabled}
      {@const svgPt = toSvgPx({ x: hole.point.x, y: hole.point.y })}
      <circle
        class="hole"
        class:pickable={jumperToolActive}
        data-hole-id={hole.id}
        cx={svgPt.x}
        cy={svgPt.y}
        r={HOLE_RADIUS_MM * SCALE}
        fill="#ffffff"
        stroke={highlightHoleId === hole.id ? 'var(--color-accent)' : '#404040'}
        stroke-width={highlightHoleId === hole.id ? 1.2 * SCALE : 0.3 * SCALE}
      />
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
      r={HOLE_RADIUS_MM * 2.2 * SCALE}
      fill="none"
      stroke="var(--color-accent)"
      stroke-width={1.2 * SCALE}
    />
  {/if}
{/if}

{#if showLabels}
  <g class="labels" aria-hidden="true">
    <!-- Column numbers along the top of the board (row a) -->
    {#each labelColumns as col (col)}
      {@const h = holeAtGrid(col, 'a')}
      {#if h}
        {@const svgPt = toSvgPx({ x: h.point.x, y: h.point.y })}
        <text
          x={svgPt.x}
          y={svgPt.y - 3 * SCALE}
          text-anchor="middle"
          font-size={2.4 * SCALE}
          fill="var(--color-muted)"
        >
          {col}
        </text>
      {/if}
    {/each}
    <!-- Row letters along the left of the board (column 1) -->
    {#each labelRows as row (row)}
      {@const h = holeAtGrid(1, row)}
      {#if h}
        {@const svgPt = toSvgPx({ x: h.point.x, y: h.point.y })}
        <text
          x={svgPt.x - 3 * SCALE}
          y={svgPt.y + 0.8 * SCALE}
          text-anchor="end"
          font-size={2.4 * SCALE}
          fill="var(--color-muted)"
        >
          {row}
        </text>
      {/if}
    {/each}
  </g>
{/if}

<style>
  .holes {
    /* Hole strokes look better with shape-rendering: geometricPrecision */
    shape-rendering: geometricPrecision;
  }

  .hole.pickable {
    cursor: crosshair;
  }

  .hole-highlight {
    pointer-events: none;
  }
</style>