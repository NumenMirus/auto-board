<script lang="ts">
  type Props = { strokeColor: string };

  let { strokeColor }: Props = $props();
</script>

<!-- Polarized capacitor: left plate is positive, right plate is negative -->
<g
  fill="none"
  stroke={strokeColor}
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <!-- Leads -->
  <line x1="0" y1="0" x2="2.7" y2="0" stroke-width="0.3" />
  <line x1="3.8" y1="0" x2="6" y2="0" stroke-width="0.3" />

  <!-- Positive plate -->
  <line x1="2.7" y1="-1.2" x2="2.7" y2="1.2" stroke-width="0.36" />

  <!-- Curved negative plate -->
  <path
    d="M 3.8 -1.2 Q 3.25 0 3.8 1.2"
    stroke-width="0.36"
  />

  <!-- Positive-terminal marker -->
  <line x1="2.28" y1="-1.72" x2="2.68" y2="-1.72" stroke-width="0.24" />
  <line x1="2.48" y1="-1.92" x2="2.48" y2="-1.52" stroke-width="0.24" />
</g>