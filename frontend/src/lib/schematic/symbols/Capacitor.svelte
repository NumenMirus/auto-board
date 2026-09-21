<script lang="ts">
  type Props = { strokeColor: string };

  let { strokeColor }: Props = $props();
</script>

<!-- Non-polarized capacitor -->
<g
  fill="none"
  stroke={strokeColor}
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <!-- Leads -->
  <line x1="0" y1="0" x2="2.7" y2="0" stroke-width="0.3" />
  <line x1="3.7" y1="0" x2="6" y2="0" stroke-width="0.3" />

  <!-- Plates -->
  <line x1="2.7" y1="-1.2" x2="2.7" y2="1.2" stroke-width="0.36" />
  <line x1="3.7" y1="-1.2" x2="3.7" y2="1.2" stroke-width="0.36" />
</g>