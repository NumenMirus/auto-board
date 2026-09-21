<script lang="ts">
  type Props = {
    strokeColor: string;
    halfCount: number;
  };

  let { strokeColor, halfCount }: Props = $props();

  const bodyLeft = 2;
  const bodyRight = 10;
  const bodyWidth = bodyRight - bodyLeft;
  const top = 0.5;
  const bottom = halfCount + 0.5;
</script>

<!-- Generic dual-inline-package IC -->
<g
  fill="none"
  stroke={strokeColor}
  stroke-linecap="round"
  stroke-linejoin="round"
>
  <!-- Left and right pin leads -->
  {#each Array(halfCount) as _, i (i)}
    <line
      x1="0"
      y1={i + 1}
      x2={bodyLeft}
      y2={i + 1}
      stroke-width="0.3"
    />

    <line
      x1={bodyRight}
      y1={i + 1}
      x2="12"
      y2={i + 1}
      stroke-width="0.3"
    />
  {/each}

  <!-- IC package body -->
  <rect
    x={bodyLeft}
    y={top}
    width={bodyWidth}
    height={halfCount}
    rx="0.2"
    fill="var(--paper-0)"
    stroke-width="0.3"
  />

  <!-- Centred DIP orientation notch -->
  <path
    d="M 5.35 0.5 A 0.65 0.65 0 0 0 6.65 0.5"
    fill="var(--paper-0)"
    stroke-width="0.3"
  />

  <!-- Pin-1 marker -->
  <circle
    cx="2.65"
    cy="1.05"
    r="0.18"
    fill={strokeColor}
    stroke="none"
  />
</g>