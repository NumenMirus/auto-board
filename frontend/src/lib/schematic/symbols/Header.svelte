<script lang="ts">
  type Props = { strokeColor: string; pins: number };
  let { strokeColor, pins }: Props = $props();
</script>

<!-- Inline pin strip: body rect with N square pads inside. -->
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
  <rect
    x={3}
    y={i - 0.3}
    width={1}
    height={0.6}
    fill="var(--ink-1)"
    stroke="none"
  />
{/each}
