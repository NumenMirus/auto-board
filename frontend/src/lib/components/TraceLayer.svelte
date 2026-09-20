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

  // Top copper is solid and bright; bottom copper is dashed (it runs on
  // the underside of the board — when the user sees two parallel traces,
  // the dashed one is on the other side). Computed lazily so the runtime
  // SCALE is read at template-time, not module-init.
  function strokeWidth(): number {
    return 0.55 * SCALE;
  }
  function dashBottom(): string {
    return `${0.7 * SCALE} ${0.4 * SCALE}`;
  }

  function segmentPoints(segment: Trace['segments'][number]): string {
    const start = toSvgPx({ x: segment.start.x, y: segment.start.y });
    const end = toSvgPx({ x: segment.end.x, y: segment.end.y });
    return `${start.x.toFixed(2)},${start.y.toFixed(2)} ${end.x.toFixed(2)},${end.y.toFixed(2)}`;
  }

  function traceColor(trace: Trace): string {
    if (highlightNetId && trace.netId !== highlightNetId) return '#D6CFBE';
    // Stable per-net color, palette drawn from the bench wire set + the
    // table of common 22-AWG silicone jacket colors.
    const palette = [
      '#1F77B4',
      '#D6332B',
      '#2A6E3F',
      '#7B3FA8',
      '#C2820F',
      '#8C564B',
      '#0E7C8C',
      '#4F4F4F',
      '#A23582'
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