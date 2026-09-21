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

  // Top copper is solid; bottom copper is dashed (it runs on the underside
  // of the board — when two parallel traces appear, the dashed one is on
  // the other side).
  function strokeWidth(): number {
    return 0.42 * SCALE;
  }
  function dashBottom(): string {
    return `${0.6 * SCALE} ${0.4 * SCALE}`;
  }

  function segmentPoints(segment: Trace['segments'][number]): string {
    const start = toSvgPx({ x: segment.start.x, y: segment.start.y });
    const end = toSvgPx({ x: segment.end.x, y: segment.end.y });
    return `${start.x.toFixed(2)},${start.y.toFixed(2)} ${end.x.toFixed(2)},${end.y.toFixed(2)}`;
  }

  function traceColor(trace: Trace): string {
    if (highlightNetId && trace.netId !== highlightNetId) return '#D6CFBE';
    // Muted, harmonized palette inspired by pencil-on-paper drafts. Each
    // hue stays distinct enough to identify a net on a busy board, but the
    // chroma is dropped so the trace doesn't shout over the components.
    const palette = [
      '#5C7AA8', // slate blue
      '#A8645C', // brick
      '#5C8C6F', // sage
      '#7E6B9A', // muted plum
      '#B08840', // ochre
      '#8C7A6E', // taupe
      '#5C8C8C', // teal
      '#7A7A7A', // graphite
      '#9A6B82'  // dusty rose
    ];
    let hash = 0;
    for (let i = 0; i < trace.netId.length; i += 1) {
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
          stroke-width={strokeWidth()}
          stroke-dasharray={segment.layer === 'bottom' ? dashBottom() : undefined}
          stroke-linecap="round"
          stroke-linejoin="round"
          opacity={dimmed ? 0.35 : 1}
        />
      {/each}
      {#if isSelected}
        {#each trace.segments as segment, segIndex ('selected-' + segIndex)}
          {@const points = segmentPoints(segment)}
          <polyline
            {points}
            fill="none"
            stroke="var(--accent-1)"
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
    transition: opacity 180ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .trace.dimmed {
    opacity: 0.35;
  }
</style>