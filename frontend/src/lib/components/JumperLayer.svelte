<script lang="ts">
  import type { Jumper } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    jumpers: Jumper[];
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    selectedId?: string | null;
    onSelect?: ((kind: 'component' | 'jumper', id: string) => void) | undefined;
  };
  let { jumpers, SCALE, toSvgPx, selectedId = null, onSelect = undefined }: Props = $props();

  // Visible stroke widths per layer (the backend encodes crossings by
  // promoting a jumper to the upper layer).
  const STROKE_LOWER = 1.2;
  const STROKE_UPPER = 1.6;

  function polylinePoints(j: Jumper): string {
    return j.path.points
      .map((p) => {
        const svgPt = toSvgPx({ x: p.x, y: p.y });
        return `${svgPt.x.toFixed(2)},${svgPt.y.toFixed(2)}`;
      })
      .join(' ');
  }

  function midpoint(j: Jumper): { x: number; y: number } | null {
    if (j.path.points.length === 0) return null;
    const mid = j.path.points[Math.floor(j.path.points.length / 2)];
    return toSvgPx({ x: mid.x, y: mid.y });
  }
</script>

<g class="jumpers">
  {#each jumpers as jumper, index (jumper.id)}
    {@const points = polylinePoints(jumper)}
    {@const mid = midpoint(jumper)}
    {@const isSelected = selectedId === jumper.id}
    <g
      class="jumper"
      class:selected={isSelected}
      data-jumper-id={jumper.id}
      data-layer={jumper.path.layer}
      role="button"
      tabindex="0"
      aria-label={`Jumper ${jumper.id}`}
      aria-pressed={isSelected}
      onclick={(e) => {
        e.stopPropagation();
        onSelect?.('jumper', jumper.id);
      }}
      onkeydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          onSelect?.('jumper', jumper.id);
        }
      }}
    >
      <polyline
        {points}
        fill="none"
        stroke={jumper.color ?? '#1f77b4'}
        stroke-width={(jumper.path.layer === 'upper' ? STROKE_UPPER : STROKE_LOWER) * SCALE}
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      {#if isSelected}
        <polyline
          {points}
          fill="none"
          stroke="var(--color-accent)"
          stroke-width={0.4 * SCALE}
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      {/if}
      {#if mid}
        <circle cx={mid.x} cy={mid.y} r={1.6 * SCALE} fill="#ffffff" stroke="#404040" stroke-width={0.4 * SCALE} />
        <text
          x={mid.x}
          y={mid.y + 0.8 * SCALE}
          text-anchor="middle"
          dominant-baseline="middle"
          font-size={2.0 * SCALE}
          fill="var(--color-fg)"
        >
          {index + 1}
        </text>
      {/if}
    </g>
  {/each}
</g>

<style>
  .jumpers {
    shape-rendering: geometricPrecision;
  }

  .jumper {
    cursor: pointer;
  }

  text {
    user-select: none;
    pointer-events: none;
  }
</style>