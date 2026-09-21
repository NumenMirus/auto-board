<script lang="ts">
  type Props = { strokeColor: string };

  let { strokeColor }: Props = $props();
</script>

<!-- ANSI resistor: longer zig-zag body -->
<path
  d="
    M 0 0
    H 0.9
    L 1.3 -0.8
    L 1.8 0.8
    L 2.3 -0.8
    L 2.8 0.8
    L 3.3 -0.8
    L 3.8 0.8
    L 4.3 -0.8
    L 4.7 0
    H 6
  "
  fill="none"
  stroke={strokeColor}
  stroke-width="0.3"
  stroke-linecap="round"
  stroke-linejoin="round"
/>