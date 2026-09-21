<script lang="ts">
  type Props = { strokeColor: string };
  let { strokeColor }: Props = $props();
</script>

<!-- Diode triangle + cathode bar near pin 2 -->
<line x1={0} y1={0} x2={2} y2={0} stroke="var(--ink-1)" stroke-width="0.3" />
<line x1={4} y1={0} x2={6} y2={0} stroke="var(--ink-1)" stroke-width="0.3" />
<polygon
  points="2,-1 2,1 4,0"
  fill="var(--paper-0)"
  stroke={strokeColor}
  stroke-width="0.3"
/>
<line
  x1={4}
  y1={-1}
  x2={4}
  y2={1}
  stroke={strokeColor}
  stroke-width="0.4"
/>
