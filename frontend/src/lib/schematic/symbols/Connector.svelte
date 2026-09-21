<script lang="ts">
  type Props = { strokeColor: string; pins: number };
  let { strokeColor, pins }: Props = $props();
</script>

<!-- Inline connector: body rect with N circular pad sockets inside. -->
{#each Array(pins) as _, i (i)}
  <line x1={0} y1={i} x2={2} y2={i} stroke="var(--ink-1)" stroke-width="0.3" />
{/each}
<rect
  x={2}
  y={-0.5}
  width={3}
  height={pins}
  fill="var(--paper-0)"
  stroke={strokeColor}
  stroke-width="0.3"
/>
{#each Array(pins) as _, i (i)}
  <circle
    cx={3.5}
    cy={i}
    r={0.3}
    fill="var(--paper-0)"
    stroke="var(--ink-1)"
    stroke-width="0.25"
  />
{/each}
