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

  // Lower-layer wires draw as solid; upper-layer wires (those crossing at
  // least one other jumper) draw as a slightly fatter line with a faint
  // outer halo so crossings read at a glance.
  const STROKE_LOWER = 0.55;
  const STROKE_UPPER = 0.7;
  const HALO_UPPER = 1.6;

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

  function labelOffset(j: Jumper): { x: number; y: number } {
    // Nudge the number above the wire so it doesn't sit ON the line.
    if (j.path.points.length < 2) return { x: 0, y: -2 };
    const mid = j.path.points[Math.floor(j.path.points.length / 2)];
    const next = j.path.points[Math.floor(j.path.points.length / 2) + 1] ?? mid;
    const dx = next.x - mid.x;
    const dy = next.y - mid.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    return { x: nx * 2.2, y: ny * 2.2 };
  }
</script>

<g class="jumpers">
  {#each jumpers as jumper, index (jumper.id)}
    {@const points = polylinePoints(jumper)}
    {@const mid = midpoint(jumper)}
    {@const off = labelOffset(jumper)}
    {@const isSelected = selectedId === jumper.id}
    {@const isUpper = jumper.path.layer === 'upper'}
    {@const stroke = jumper.color ?? '#1F77B4'}
    <g
      class="jumper"
      class:selected={isSelected}
      class:upper={isUpper}
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
      {#if isUpper}
        <!-- Crossing halo: a translucent wider stroke below the actual wire
             so the eye reads "this wire is on top". -->
        <polyline
          {points}
          fill="none"
          stroke="#FFFFFF"
          stroke-opacity="0.85"
          stroke-width={HALO_UPPER * SCALE}
          stroke-linecap="round"
          stroke-linejoin="round"
          pointer-events="none"
        />
      {/if}
      <polyline
        {points}
        fill="none"
        stroke={stroke}
        stroke-width={(isUpper ? STROKE_UPPER : STROKE_LOWER) * SCALE}
        stroke-linecap="round"
        stroke-linejoin="round"
      />
      {#if isSelected}
        <polyline
          {points}
          fill="none"
          stroke="var(--accent-1)"
          stroke-width={0.5 * SCALE}
          stroke-linecap="round"
          stroke-linejoin="round"
          opacity="0.8"
        />
      {/if}
      {#if mid}
        <circle
          cx={mid.x + off.x}
          cy={mid.y + off.y}
          r={1.6 * SCALE}
          fill="#FFFFFF"
          stroke="#3A332B"
          stroke-width={0.4 * SCALE}
        />
        <text
          x={mid.x + off.x}
          y={mid.y + off.y + 0.9 * SCALE}
          text-anchor="middle"
          dominant-baseline="middle"
          font-family="'JetBrains Mono', monospace"
          font-size="2.2"
          font-weight="600"
          fill="#181715"
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