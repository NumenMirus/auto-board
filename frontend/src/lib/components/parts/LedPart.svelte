<script lang="ts">
  import type { Point2D } from '../../geometry';

  /**
   * Through-hole LED — colored translucent dome on a dark epoxy base
   * (the "flange"), with a flat rim around the dome that catches light
   * and a brighter specular highlight to sell the plastic look. Two
   * leads exit from the base toward the breadboard pins.
   *
   * The dome's color is derived from the value field (red/green/blue/
   * yellow/white/orange) when present, defaulting to a saturated red.
   */
  type Props = {
    aSvg: Point2D;
    bSvg: Point2D;
    SCALE: number;
    label: string;
    value: string | null;
    locked: boolean;
    selected: boolean;
    dragging: boolean;
  };
  let { aSvg, bSvg, SCALE, label, value, locked, selected, dragging }: Props = $props();

  const dx = $derived(bSvg.x - aSvg.x);
  const dy = $derived(bSvg.y - aSvg.y);
  const leadLen = $derived(Math.hypot(dx, dy));
  const angleDeg = $derived((Math.atan2(dy, dx) * 180) / Math.PI);

  // Pick a hue that matches the LED's color value if possible; default
  // to a saturated red (the most common through-hole LED).
  function ledColor(v: string | null): string {
    if (v === null) return '#E63A30';
    const lower = v.toLowerCase();
    if (/red|crimson|rd/i.test(lower)) return '#E63A30';
    if (/green|gn/i.test(lower)) return '#34B556';
    if (/blue|bl/i.test(lower)) return '#2A6BD0';
    if (/yellow|amber|yl/i.test(lower)) return '#F2C12E';
    if (/white|wh/i.test(lower)) return '#EFEAD4';
    if (/orange|or/i.test(lower)) return '#F08A24';
    if (/purple|violet|pink|magenta/i.test(lower)) return '#B85AC8';
    if (/cyan|teal/i.test(lower)) return '#1FBFC2';
    return '#E63A30';
  }

  // Same hue, slightly darker — used as the dome's stroke to give the
  // plastic edge some definition against the breadboard.
  function ledEdge(color: string): string {
    if (color === '#EFEAD4') return '#A8A294';
    // For saturated colors, darken by ~50% luminance.
    if (color.startsWith('#') && color.length === 7) {
      const r = parseInt(color.slice(1, 3), 16);
      const g = parseInt(color.slice(3, 5), 16);
      const b = parseInt(color.slice(5, 7), 16);
      return `rgb(${Math.round(r * 0.45)}, ${Math.round(g * 0.45)}, ${Math.round(b * 0.45)})`;
    }
    return color;
  }

  const domeColor = $derived(ledColor(value));
  const domeEdge = $derived(ledEdge(domeColor));

  // Geometry: a darker flange ring around the dome, and the dome itself
  // sits raised on the ring. The leads exit from underneath.
  const flangeR = 2.2; // mm
  const flangeH = 1.3; // mm
  const domeR = 1.85;  // mm

  // Lead stubs: from the pin centers toward the flange bottom.
  const flangeBottomX = $derived(flangeR * 0.55);
</script>

<g
  class="part-led"
  class:locked
  class:selected
  class:dragging
  transform={`translate(${(aSvg.x + bSvg.x) / 2} ${(aSvg.y + bSvg.y) / 2}) rotate(${angleDeg}) scale(${SCALE})`}
>
  <!-- Lead stubs from each pin toward the flange base. -->
  <line
    x1={-leadLen / 2}
    x2={-flangeBottomX - 0.2}
    y1="0"
    y2="0"
    stroke="#7E766A"
    stroke-width="0.5"
    stroke-linecap="round"
  />
  <line
    x1={flangeBottomX + 0.2}
    x2={leadLen / 2}
    y1="0"
    y2="0"
    stroke="#7E766A"
    stroke-width="0.5"
    stroke-linecap="round"
  />

  <!-- Dark epoxy flange (the flat ring under the dome) -->
  <rect
    x={-flangeR}
    y={-flangeH / 2}
    width={flangeR * 2}
    height={flangeH}
    rx={flangeH / 2}
    ry={flangeH / 2}
    fill={locked ? '#D8D2C2' : '#1F1B17'}
    fill-opacity={dragging ? 0.45 : 1}
    stroke={selected ? 'var(--accent-1)' : '#000000'}
    stroke-width={selected ? 0.6 : 0.18}
  />

  <!-- Colored translucent dome — drawn as a half-circle on top of the
       flange, so the dome reads as raised above the base. -->
  <path
    d={`M ${-domeR + 0.05} 0 A ${domeR} ${domeR} 0 0 1 ${domeR - 0.05} 0 Z`}
    fill={domeColor}
    fill-opacity={dragging ? 0.5 : 0.92}
    stroke={selected ? 'var(--accent-1)' : domeEdge}
    stroke-width={selected ? 0.6 : 0.18}
  />

  <!-- Inner rim line for definition at the dome base -->
  <line
    x1={-domeR * 0.95}
    x2={domeR * 0.95}
    y1="0"
    y2="0"
    stroke={domeEdge}
    stroke-width="0.12"
    stroke-linecap="round"
    opacity={dragging ? 0.4 : 0.7}
  />

  <!-- Primary specular highlight (large) -->
  <ellipse
    cx={-domeR * 0.32}
    cy={-domeR * 0.5}
    rx={domeR * 0.36}
    ry={domeR * 0.22}
    fill="rgba(255,255,255,0.55)"
    pointer-events="none"
  />

  <!-- Secondary specular pinprick -->
  <ellipse
    cx={-domeR * 0.18}
    cy={-domeR * 0.55}
    rx={domeR * 0.1}
    ry={domeR * 0.07}
    fill="rgba(255,255,255,0.85)"
    pointer-events="none"
  />

  <!-- Cathode marker: a small flat notch on the pin-2 side of the flange -->
  <line
    x1={flangeR - 0.55}
    x2={flangeR - 0.05}
    y1={-flangeH / 2 + 0.18}
    y2={-flangeH / 2 + 0.18}
    stroke="#9A9384"
    stroke-width="0.14"
    stroke-linecap="round"
  />

  <!-- Reference designator below the body -->
  <text
    x="0"
    y={flangeH / 2 + 0.95}
    text-anchor="middle"
    dominant-baseline="middle"
    font-family="'JetBrains Mono', monospace"
    font-size="1.4"
    font-weight="600"
    fill="#181715"
    pointer-events="none"
  >
    {label}
  </text>
</g>

<style>
  .part-led text {
    user-select: none;
  }
</style>