<script lang="ts">
  import type { Via } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    vias: Via[];
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
  };
  let { vias, SCALE, toSvgPx }: Props = $props();
</script>

<g class="vias" aria-hidden="true">
  {#each vias as via, index (index)}
    {@const svgPt = toSvgPx({ x: via.point.x, y: via.point.y })}
    <circle
      class="via-ring"
      cx={svgPt.x}
      cy={svgPt.y}
      r={(via.diameterMm / 2) * SCALE}
      fill="#ffffff"
      stroke="#404040"
      stroke-width={0.15 * SCALE}
    />
    <circle
      class="via-drill"
      cx={svgPt.x}
      cy={svgPt.y}
      r={(via.drillMm / 2) * SCALE}
      fill="#1a1a1a"
    />
  {/each}
</g>

<style>
  .vias {
    shape-rendering: geometricPrecision;
  }
</style>
