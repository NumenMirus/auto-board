<script lang="ts">
  type Props = { strokeColor: string };
  let { strokeColor }: Props = $props();
</script>

<!-- TACT-SW-4P: two parallel bars + dashed actuator diagonal between. -->
<line x1={0} y1={0} x2={1} y2={0} stroke="var(--ink-1)" stroke-width="0.3" />
<line x1={5} y1={0} x2={6} y2={0} stroke="var(--ink-1)" stroke-width="0.3" />
<line x1={0} y1={3} x2={1} y2={3} stroke="var(--ink-1)" stroke-width="0.3" />
<line x1={5} y1={3} x2={6} y2={3} stroke="var(--ink-1)" stroke-width="0.3" />
<line x1={1} y1={0} x2={5} y2={0} stroke={strokeColor} stroke-width="0.5" />
<line x1={1} y1={3} x2={5} y2={3} stroke={strokeColor} stroke-width="0.5" />
<line
  x1={1}
  y1={0}
  x2={5}
  y2={3}
  stroke={strokeColor}
  stroke-width="0.3"
  stroke-dasharray="0.5 0.4"
/>
