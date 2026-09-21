<script lang="ts">
  type Props = { strokeColor: string };

  let { strokeColor }: Props = $props();
</script>

<g
  fill="none"
  stroke={strokeColor}
  stroke-width="0.3"
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <!-- Three pins -->
  <line x1="0" y1="0" x2="2" y2="0" />
  <line x1="0" y1="2" x2="2" y2="2" />
  <line x1="0" y1="4" x2="2" y2="4" />

  <!-- TO-92 body -->
  <path
    d="M 2 0
       H 4
       Q 5 0 5 1
       V 3
       Q 5 4 4 4
       H 2
       Z"
    fill="var(--paper-0)"
  />

  <!-- Simple transistor indicator -->
  <line x1="3.5" y1="0.8" x2="3.5" y2="3.2" />
</g>
