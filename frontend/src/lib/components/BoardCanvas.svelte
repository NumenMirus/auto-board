<script lang="ts">
  import { untrack } from 'svelte';
  import HoleLayer from './HoleLayer.svelte';
  import ComponentLayer from './ComponentLayer.svelte';
  import JumperLayer from './JumperLayer.svelte';
  import TraceLayer from './TraceLayer.svelte';
  import ViaLayer from './ViaLayer.svelte';
  import { boardToSvg, type Point2D } from '../geometry';
  import type { AnyBoardModel, AnyLayout, PerfboardModel, TraceLayout } from '../types';

  type Props = {
    board: AnyBoardModel;
    layout?: AnyLayout | undefined;
    showLabels?: boolean;
    onPlacementMove?: ((componentRef: string, newAnchorHoleId: string) => void) | undefined;
    onRotate?: ((componentRef: string) => void) | undefined;
    onLockToggle?: ((componentRef: string) => void) | undefined;
    onDelete?: ((kind: 'component' | 'jumper' | 'trace', id: string) => void) | undefined;
    onJumperCreate?:
      | ((startHoleId: string, endHoleId: string) => void)
      | undefined;
    onSelect?: ((kind: 'component' | 'jumper' | 'trace', id: string) => void) | undefined;
    selectedId?: string | null | undefined;
    selectedKind?: ('component' | 'jumper' | 'trace' | null) | undefined;
    jumperToolActive?: boolean | undefined;
    jumperStartHoleId?: string | null | undefined;
  };
  let {
    board,
    layout = undefined,
    showLabels = true,
    onPlacementMove = undefined,
    onRotate = undefined,
    onLockToggle = undefined,
    onDelete = undefined,
    onJumperCreate = undefined,
    onSelect = undefined,
    selectedId = null,
    selectedKind = null,
    jumperToolActive = false,
    jumperStartHoleId = null
  }: Props = $props();

  let pendingStart = $state<string | null>(untrack(() => jumperStartHoleId));
  $effect(() => {
    pendingStart = jumperStartHoleId;
  });

  const SCALE = 4;

  const boardExtent = $derived.by(() => {
    const DEFAULT = { minX: 0, minY: -15, maxX: 80, maxY: 45 };
    if (board.zones.length === 0) return DEFAULT;
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (const zone of board.zones) {
      for (const p of zone.polygon) {
        if (p.x < minX) minX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.x > maxX) maxX = p.x;
        if (p.y > maxY) maxY = p.y;
      }
    }
    if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
      return DEFAULT;
    }
    return { minX, minY, maxX, maxY };
  });

  let viewX = $state(0);
  let viewY = $state(0);
  let viewW = $state(80);
  let viewH = $state(60);

  $effect.pre(() => {
    viewX = boardExtent.minX - 2;
    viewY = boardExtent.minY - 2;
    viewW = boardExtent.maxX - boardExtent.minX + 4;
    viewH = boardExtent.maxY - boardExtent.minY + 4;
  });

  const viewBoxAttr = $derived(
    `${viewX * SCALE} ${viewY * SCALE} ${viewW * SCALE} ${viewH * SCALE}`
  );

  function toSvgPx(p: Point2D): Point2D {
    return boardToSvg(p, SCALE);
  }

  // View is fixed to the board extent (no pan/zoom interactivity).

  function onCanvasClick(event: MouseEvent): void {
    if (!jumperToolActive) return;
    const target = event.target as Element | null;
    const holeId = target?.getAttribute?.('data-hole-id');
    if (holeId === null || holeId === undefined || holeId === '') return;
    if (pendingStart === null) {
      pendingStart = holeId;
    } else if (pendingStart === holeId) {
      pendingStart = null;
    } else {
      onJumperCreate?.(pendingStart, holeId);
      pendingStart = null;
    }
  }

  $effect(() => {
    function handler(event: KeyboardEvent): void {
      const t = event.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === 'r' && selectedKind === 'component' && selectedId !== null) {
        event.preventDefault();
        onRotate?.(selectedId);
      } else if (key === 'l' && selectedKind === 'component' && selectedId !== null) {
        event.preventDefault();
        onLockToggle?.(selectedId);
      } else if ((key === 'delete' || key === 'backspace') && selectedId !== null && selectedKind !== null) {
        event.preventDefault();
        onDelete?.(selectedKind, selectedId);
      } else if (key === 'escape') {
        if (pendingStart !== null) pendingStart = null;
      }
    }
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
    };
  });

  export function holeAt(clientX: number, clientY: number): string | null {
    const svg = rootEl;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return null;
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const worldX = viewX + (localX / rect.width) * viewW;
    const worldY = viewY + (localY / rect.height) * viewH;
    let bestId: string | null = null;
    let bestDist = Number.POSITIVE_INFINITY;
    const SNAP_MM = 2.5;
    for (const hole of board.holes) {
      const dx = hole.point.x - worldX;
      const dy = hole.point.y - worldY;
      const d = Math.hypot(dx, dy);
      if (d < bestDist) {
        bestDist = d;
        bestId = hole.id;
      }
    }
    if (bestId !== null && bestDist <= SNAP_MM) {
      return bestId;
    }
    return null;
  }

  let rootEl: SVGSVGElement | null = $state(null);

  function isPerfboardModel(b: AnyBoardModel): b is PerfboardModel {
    return !('electricalGroups' in b);
  }
  const isPerfboard = $derived(isPerfboardModel(board));

  function isTraceLayout(l: AnyLayout): l is TraceLayout {
    return 'traces' in l;
  }

  const tiePointGroups = $derived(
    isPerfboard ? [] : (board as Exclude<AnyBoardModel, PerfboardModel>).electricalGroups.filter((g) => g.kind === 'tie-point')
  );

  function groupBounds(group: { holeIds: string[] }): {
    x: number;
    y: number;
    w: number;
    h: number;
  } | null {
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    let found = false;
    const byId = new Map(board.holes.map((h) => [h.id, h]));
    for (const hid of group.holeIds) {
      const h = byId.get(hid);
      if (!h || !h.enabled) continue;
      found = true;
      if (h.point.x < minX) minX = h.point.x;
      if (h.point.y < minY) minY = h.point.y;
      if (h.point.x > maxX) maxX = h.point.x;
      if (h.point.y > maxY) maxY = h.point.y;
    }
    if (!found) return null;
    const pad = board.pitchMm / 2;
    return {
      x: minX - pad,
      y: minY - pad,
      w: maxX - minX + 2 * pad,
      h: maxY - minY + 2 * pad
    };
  }

  interface RailStrip {
    id: string;
    y: number;
    x: number;
    w: number;
    color: 'plus' | 'minus';
    label: string;
  }

  const railStrips = $derived.by((): RailStrip[] => {
    if (isPerfboard) return [];
    const out: RailStrip[] = [];
    const railGroups = (board as Exclude<AnyBoardModel, PerfboardModel>).electricalGroups.filter(
      (g) => g.kind === 'rail'
    );
    const byId = new Map(board.holes.map((h) => [h.id, h]));
    for (const g of railGroups) {
      let minX = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let y = 0;
      for (const hid of g.holeIds) {
        const h = byId.get(hid);
        if (!h) continue;
        if (h.point.x < minX) minX = h.point.x;
        if (h.point.x > maxX) maxX = h.point.x;
        y = h.point.y;
      }
      if (!Number.isFinite(minX)) continue;
      const isPlus = g.id.includes('-plus-');
      // Strip identifier carries its polarity in the name. Strip any rail-
      // internal group suffix so the label prints "top-plus" / "bottom-minus".
      const label = isPlus ? '+' : '−';
      out.push({
        id: g.id,
        y: y - board.pitchMm / 2,
        x: minX - board.pitchMm / 2,
        w: maxX - minX + board.pitchMm,
        color: isPlus ? 'plus' : 'minus',
        label
      });
    }
    return out;
  });

  const labelColumns = $derived.by((): number[] => {
    const totalCols = isPerfboard ? (board as PerfboardModel).cols : (board as { metadata: { columns: number } }).metadata.columns;
    const cols: number[] = [];
    for (let c = 1; c <= totalCols; c += 1) {
      if (c === 1 || c === 5 || c % 5 === 0) cols.push(c);
    }
    return cols;
  });
  const labelRows = $derived.by((): string[] => {
    if (isPerfboard) {
      const totalRows = (board as PerfboardModel).rows;
      const rows: string[] = [];
      for (let r = 1; r <= totalRows; r += 1) {
        if (r === 1 || r === 5 || r % 5 === 0) rows.push(String(r));
      }
      return rows;
    }
    return (board as { metadata: { rows: string[] } }).metadata.rows;
  });

  function holeAtGrid(col: number, row: string) {
    return board.holes.find((h) => h.grid.col === col && h.grid.row === row);
  }

  // Board footprint rectangle (the actual plastic surface). Derived from
  // the model's own "main" zone so it always matches the hole grid exactly
  // (both breadboards and perfboards carry a main zone from the backend);
  // only a boardless-zone model falls back to a generic rectangle.
  const boardFootprint = $derived.by(() => {
    const main = board.zones.find((z) => z.kind === 'main');
    if (main) {
      let minX = Number.POSITIVE_INFINITY;
      let minY = Number.POSITIVE_INFINITY;
      let maxX = Number.NEGATIVE_INFINITY;
      let maxY = Number.NEGATIVE_INFINITY;
      for (const p of main.polygon) {
        if (p.x < minX) minX = p.x;
        if (p.y < minY) minY = p.y;
        if (p.x > maxX) maxX = p.x;
        if (p.y > maxY) maxY = p.y;
      }
      return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
    }
    if (isPerfboard) {
      const p = board as PerfboardModel;
      return {
        x: -p.pitchMm / 2,
        y: -p.pitchMm / 2,
        w: (p.cols - 1) * p.pitchMm + p.pitchMm,
        h: (p.rows - 1) * p.pitchMm + p.pitchMm
      };
    }
    return { x: -2, y: -15, w: 80, h: 60 };
  });

  // Center-gap polygon for the visual "channel" between rows e and f.
  const centerGap = $derived.by(() => {
    if (isPerfboard) return null;
    const gap = (board as Exclude<AnyBoardModel, PerfboardModel>).zones.find(
      (z) => z.kind === 'center-gap'
    );
    if (!gap) return null;
    return gap.polygon.map((p) => toSvgPx(p));
  });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<svg
  bind:this={rootEl}
  class="board-canvas"
  viewBox={viewBoxAttr}
  preserveAspectRatio="xMidYMid meet"
  onclick={onCanvasClick}
  role="application"
  aria-label={isPerfboard ? 'Perfboard editor canvas' : 'Breadboard editor canvas'}
>
  <defs>
    <!-- Plastic-board gradient: top edge a touch lighter, bottom a touch
         cooler. Both stops sit in the same hue so the surface still reads
         as one piece of ABS plastic. -->
    <linearGradient id="board-plastic" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FBFAF6" />
      <stop offset="1" stop-color="#EFEBE0" />
    </linearGradient>
    <linearGradient id="rail-plus-grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#C72922" />
      <stop offset="0.5" stop-color="#D6332B" />
      <stop offset="1" stop-color="#C72922" />
    </linearGradient>
    <linearGradient id="rail-minus-grad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#0E0E0E" />
      <stop offset="0.5" stop-color="#262624" />
      <stop offset="1" stop-color="#0E0E0E" />
    </linearGradient>
    <!-- Reusable shadow for raised board surface. -->
    <filter id="board-shadow" x="-5%" y="-5%" width="110%" height="120%">
      <feDropShadow dx="0" dy="1" stdDeviation="1.2" flood-opacity="0.10" />
    </filter>
  </defs>

  {#if true}
    {@const fp = boardFootprint}
    {@const fpTL = toSvgPx({ x: fp.x, y: fp.y })}
    {@const fpW = fp.w * SCALE}
    {@const fpH = fp.h * SCALE}
    <!-- ===== Plastic body ===== -->
    <g aria-hidden="true">
      <rect
        x={fpTL.x}
        y={fpTL.y}
        width={fpW}
        height={fpH}
        rx="3"
        ry="3"
        fill="url(#board-plastic)"
        stroke="#D6CFBE"
        stroke-width="0.6"
        filter="url(#board-shadow)"
      />

      <!-- Faint ruled grid behind the holes. Each pitch is 2.54 mm. -->
      {#each labelColumns as col (col)}
        {@const h = holeAtGrid(col, labelRows[0])}
        {#if h}
          {@const x = toSvgPx({ x: h.point.x, y: fp.y }).x}
          <line
            x1={x}
            x2={x}
            y1={fpTL.y + 2}
            y2={fpTL.y + fpH - 2}
            stroke="rgba(24, 23, 21, 0.025)"
            stroke-width="0.3"
          />
        {/if}
      {/each}
    </g>
  {/if}

  {#if !isPerfboard}
    <!-- ===== Tie-point group shading ===== -->
    <g class="tie-point-shading" aria-hidden="true">
      {#each tiePointGroups as group (group.id)}
        {@const b = groupBounds(group)}
        {#if b}
          {@const tl = toSvgPx({ x: b.x, y: b.y })}
          <rect
            x={tl.x}
            y={tl.y}
            width={b.w * SCALE}
            height={b.h * SCALE}
            rx="1"
            ry="1"
            fill="rgba(11, 77, 255, 0.045)"
            stroke="rgba(11, 77, 255, 0.16)"
            stroke-width="0.4"
          />
        {/if}
      {/each}
    </g>

    <!-- ===== Center-gap channel ===== -->
    {#if centerGap && centerGap.length > 1}
      <polygon
        points={centerGap.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ')}
        fill="rgba(24, 23, 21, 0.04)"
        stroke="rgba(24, 23, 21, 0.10)"
        stroke-width="0.3"
      />
    {/if}

    <!-- ===== Rail strips ===== -->
    <g class="rails" aria-hidden="true">
      {#each railStrips as strip (strip.id)}
        {@const tl = toSvgPx({ x: strip.x, y: strip.y })}
        <rect
          x={tl.x}
          y={tl.y}
          width={strip.w * SCALE}
          height={board.pitchMm * SCALE}
          rx="0.6"
          ry="0.6"
          fill={strip.color === 'plus' ? 'url(#rail-plus-grad)' : 'url(#rail-minus-grad)'}
          stroke={strip.color === 'plus' ? '#9A1F1B' : '#000000'}
          stroke-width="0.4"
        />
        <text
          x={tl.x + (strip.w * SCALE) / 2}
          y={tl.y + (board.pitchMm * SCALE) / 2 + 0.9 * SCALE}
          text-anchor="middle"
          dominant-baseline="middle"
          font-family="'JetBrains Mono', monospace"
          font-size="2.6"
          font-weight="700"
          fill={strip.color === 'plus' ? '#FFE9E6' : '#E8E6E0'}
        >
          {strip.label}
        </text>
      {/each}
    </g>
  {/if}

  <!-- ===== Holes + labels ===== -->
  <HoleLayer
    {board}
    {showLabels}
    {SCALE}
    {toSvgPx}
    {labelColumns}
    {labelRows}
    {holeAtGrid}
    {jumperToolActive}
    highlightHoleId={pendingStart}
  />

  <!-- ===== Jumpers / traces ===== -->
  {#if layout}
    {#if isTraceLayout(layout)}
      <ViaLayer vias={layout.vias} {SCALE} {toSvgPx} />
      <TraceLayer
        traces={layout.traces}
        {SCALE}
        {toSvgPx}
        selectedId={selectedKind === 'trace' ? selectedId : null}
        onSelect={(kind, id) => onSelect?.(kind, id)}
      />
    {:else}
      <JumperLayer
        jumpers={layout.jumpers}
        {SCALE}
        {toSvgPx}
        selectedId={selectedKind === 'jumper' ? selectedId : null}
        onSelect={(kind, id) => onSelect?.(kind, id)}
      />
    {/if}
  {/if}

  <!-- ===== Components ===== -->
  {#if layout}
    <ComponentLayer
      {board}
      placements={layout.placements}
      {SCALE}
      {toSvgPx}
      selectedId={selectedKind === 'component' ? selectedId : null}
      {onSelect}
      {onPlacementMove}
      holeAt={holeAt}
    />
  {/if}
</svg>

<style>
  .board-canvas {
    display: block;
    user-select: none;
    background:
      radial-gradient(ellipse at 50% 40%, #ffffff 0%, #f7f4ec 70%, #efe9d8 100%);
    border-radius: 6px;
  }

  .board-canvas:focus {
    outline: none;
  }

  .rails text {
    pointer-events: none;
    user-select: none;
  }
</style>