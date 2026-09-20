<script lang="ts">
  import type { Trace } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    traces: Trace[];
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    selectedId?: string | null;
    highlightNetId?: string | null;
    onSelect?: ((kind: 'component' | 'trace', id: string) => void) | undefined;
  };
  let {
    traces,
    SCALE,
    toSvgPx,
    selectedId = null,
    highlightNetId = null,
    onSelect = undefined
  }: Props = $props();

  // Visible stroke widths mirror JumperLayer's lower/upper convention: the
  // top (component) layer draws solid, the bottom (solder) layer draws
  // dashed so overlapping copper on the two sides of the board stays
  // readable at a glance.
  const STROKE_TOP = 1.2;
  const STROKE_BOTTOM = 1.2;
  const DASH_BOTTOM = '3 2';

  function segmentPoints(segment: Trace['segments'][number]): string {
    const start = toSvgPx({ x: segment.start.x, y: segment.start.y });
    const end = toSvgPx({ x: segment.end.x, y: segment.end.y });
    return `${start.x.toFixed(2)},${start.y.toFixed(2)} ${end.x.toFixed(2)},${end.y.toFixed(2)}`;
  }

  function traceColor(trace: Trace): string {
    if (highlightNetId && trace.netId !== highlightNetId) return '#cccccc';
    // Stable per-net hash color (same palette family as the backend renderer).
    const palette = [
      '#1f77b4',
      '#ff7f0e',
      '#2ca02c',
      '#d62728',
      '#9467bd',
      '#8c564b',
      '#e377c2',
      '#bcbd22',
      '#17becf'
    ];
    let hash = 0;
    for (let i = 0; i < trace.netId.length; i++) {
      hash = (hash * 31 + trace.netId.charCodeAt(i)) >>> 0;
    }
    return palette[hash % palette.length];
  }
</script>

<g class="traces">
  {#each traces as trace (trace.id)}
    {@const isSelected = selectedId === trace.id}
    {@const color = traceColor(trace)}
    {@const dimmed = highlightNetId !== null && trace.netId !== highlightNetId}
    <g
      class="trace"
      class:selected={isSelected}
      class:dimmed
      data-trace-id={trace.id}
      role="button"
      tabindex="0"
      aria-label={`Trace ${trace.id}`}
      aria-pressed={isSelected}
      onclick={(e) => {
        e.stopPropagation();
        onSelect?.('trace', trace.id);
      }}
      onkeydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          e.stopPropagation();
          onSelect?.('trace', trace.id);
        }
      }}
    >
      {#each trace.segments as segment, segIndex (segIndex)}
        {@const points = segmentPoints(segment)}
        <polyline
          {points}
          fill="none"
          stroke={color}
          stroke-width={(segment.layer === 'top' ? STROKE_TOP : STROKE_BOTTOM) * SCALE}
          stroke-dasharray={segment.layer === 'bottom' ? DASH_BOTTOM : undefined}
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      {/each}
      {#if isSelected}
        {#each trace.segments as segment, segIndex ('selected-' + segIndex)}
          {@const points = segmentPoints(segment)}
          <polyline
            {points}
            fill="none"
            stroke="var(--color-accent)"
            stroke-width={0.4 * SCALE}
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        {/each}
      {/if}
    </g>
  {/each}
</g>

<style>
  .traces {
    shape-rendering: geometricPrecision;
  }

  .trace {
    cursor: pointer;
    transition: opacity 150ms ease-out;
  }

  .trace.dimmed {
    opacity: 0.35;
  }
</style>
