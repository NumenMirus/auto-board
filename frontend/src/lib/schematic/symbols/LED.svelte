<script lang="ts">
  type Props = { strokeColor: string };

  let { strokeColor }: Props = $props();
</script>

<!-- LED: diode with two light-emission arrows -->
<g fill="none" stroke={strokeColor} stroke-linecap="round" stroke-linejoin="round">
  <!-- Leads -->
  <line x1="0" y1="0" x2="2" y2="0" stroke-width="0.3" />
  <line x1="4" y1="0" x2="6" y2="0" stroke-width="0.3" />

  <!-- Diode body -->
  <path d="M 2 -1 L 2 1 L 4 0 Z" fill="var(--paper-0)" stroke-width="0.3" />

  <!-- Cathode bar -->
  <line x1="4" y1="-1" x2="4" y2="1" stroke-width="0.36" />

  <!-- Light emission arrows -->

  <!-- Light emission arrows: above the diode, pointing outward -->
  <path
    d="
    M 3.15 -1.25 L 4.05 -2.05
    M 3.67 -2.05 L 4.05 -2.05 L 3.96 -1.67

    M 4.05 -1.15 L 4.95 -1.95
    M 4.57 -1.95 L 4.95 -1.95 L 4.86 -1.57
  "
    fill="none"
    stroke={strokeColor}
    stroke-width="0.28"
    stroke-linecap="round"
    stroke-linejoin="round"
  />
</g>
