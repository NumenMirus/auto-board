<script lang="ts">
  import { untrack } from 'svelte';
  import HoleLayer from './HoleLayer.svelte';
  import ComponentLayer from './ComponentLayer.svelte';
  import JumperLayer from './JumperLayer.svelte';
  import { boardToSvg, type Point2D } from '../geometry';
  import type { BreadboardModel, Layout } from '../types';

  // Props (Svelte 5 runes mode — NO legacy `export let`).
  type Props = {
    board: BreadboardModel;
    layout?: Layout | undefined;
    showLabels?: boolean;
    // Optional interactivity callbacks. All default to a no-op so existing
    // read-only callers (e.g. the SVG-export preview) can keep using this
    // component unchanged. The canvas NEVER mutates layout state itself;
    // it only emits intents. The parent page wires the callbacks to
    // `projectStore.applyLayoutMutation` (and a debounced validate call).
    onPlacementMove?: ((componentRef: string, newAnchorHoleId: string) => void) | undefined;
    onRotate?: ((componentRef: string) => void) | undefined;
    onLockToggle?: ((componentRef: string) => void) | undefined;
    onDelete?: ((kind: 'component' | 'jumper', id: string) => void) | undefined;
    onJumperCreate?:
      | ((startHoleId: string, endHoleId: string) => void)
      | undefined;
    onSelect?: ((kind: 'component' | 'jumper', id: string) => void) | undefined;
    // The currently-selected entity id (component ref or jumper id). Drives
    // stroke styling in the layers and the keyboard-shortcut handlers.
    selectedId?: string | null | undefined;
    selectedKind?: ('component' | 'jumper' | null) | undefined;
    // When true, the canvas routes click-to-create-jumper interactions:
    // the first click on a hole records the start, the second emits
    // `onJumperCreate(start, end)`. A second click on the same hole cancels.
    jumperToolActive?: boolean | undefined;
    // The id of the hole currently being eyed as the first endpoint of a
    // pending jumper — drawn as a ring by HoleLayer.
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

  // First endpoint of a pending jumper (jumper tool: first hole clicked).
  // Lives at the canvas scope so HoleLayer / onPointerDown / onKeydown
  // can share it. Synced from the prop on every change so a parent that
  // controls it externally (e.g. an "esc to cancel" toolbar button) wins.
  let pendingStart = $state<string | null>(untrack(() => jumperStartHoleId));
  $effect(() => {
    pendingStart = jumperStartHoleId;
  });

  // Tunable scale (SVG units per millimetre). 4.0 matches the backend's
  // default RenderOptions.width_scale, so visual coordinates are 1:1 with
  // the SVG export.
  const SCALE = 4;

  // Derive an initial viewBox from the board extent. We add a small margin
  // so rails (which extend below y=0 in board space) are visible.
  const boardExtent = $derived.by(() => {
    let minX = 0;
    let minY = -15;
    let maxX = 80;
    let maxY = 45;
    if (board.zones.length > 0) {
      for (const zone of board.zones) {
        for (const p of zone.polygon) {
          if (p.x < minX) minX = p.x;
          if (p.y < minY) minY = p.y;
          if (p.x > maxX) maxX = p.x;
          if (p.y > maxY) maxY = p.y;
        }
      }
    }
    return { minX, minY, maxX, maxY };
  });

  // Pan/zoom viewBox state. Stored in board-mm space so transforms are
  // straightforward; the SVG re-maps to pixel space via the `SCALE` constant.
  let viewX = $state(0);
  let viewY = $state(0);
  let viewW = $state(80);
  let viewH = $state(60);

  // Snap viewBox to the board on first render so the user doesn't see an
  // empty canvas. `effect.pre` ensures it runs before children render.
  $effect.pre(() => {
    viewX = boardExtent.minX - 2;
    viewY = boardExtent.minY - 2;
    viewW = boardExtent.maxX - boardExtent.minX + 4;
    viewH = boardExtent.maxY - boardExtent.minY + 4;
  });

  const viewBoxAttr = $derived(`${viewX} ${viewY} ${viewW} ${viewH}`);

  // Transform a point in board-mm space to SVG pixel space (used by
  // pointer-event handlers that work in client coords).
  function toSvgPx(p: Point2D): Point2D {
    return boardToSvg(p, SCALE);
  }

  // ---- Pan/zoom --------------------------------------------------------
  let isPanning = false;
  let panStart: { x: number; y: number; vx: number; vy: number } | null = null;

  function onPointerDown(event: PointerEvent): void {
    if (event.button !== 0) return;
    isPanning = true;
    panStart = { x: event.clientX, y: event.clientY, vx: viewX, vy: viewY };
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: PointerEvent): void {
    if (!isPanning || !panStart) return;
    const dx = event.clientX - panStart.x;
    const dy = event.clientY - panStart.y;
    const svg = event.currentTarget as SVGSVGElement;
    // Pan in the SVG's local space: convert screen px to world units.
    const worldDx = (dx * viewW) / svg.clientWidth;
    const worldDy = (dy * viewH) / svg.clientHeight;
    viewX = panStart.vx - worldDx;
    viewY = panStart.vy - worldDy;
  }

  function onPointerUp(event: PointerEvent): void {
    isPanning = false;
    panStart = null;
    (event.currentTarget as Element).releasePointerCapture?.(event.pointerId);
  }

  // ---- Jumper tool: click two holes to make a wire --------------------
  // The SVG itself catches hole clicks via HoleLayer's stopPropagation, so
  // a click on empty canvas space never reaches the jumper-tool state
  // machine. That keeps the tool predictable: only deliberate hole picks
  // count.
  function onCanvasClick(event: MouseEvent): void {
    if (!jumperToolActive) return;
    const target = event.target as Element | null;
    // Hole clicks carry `data-hole-id`; everything else (rails, shading,
    // jumpers, components) is ignored here.
    const holeId = target?.getAttribute?.('data-hole-id');
    if (holeId === null || holeId === undefined || holeId === '') return;
    if (pendingStart === null) {
      pendingStart = holeId;
    } else if (pendingStart === holeId) {
      // Clicked the same hole twice -> cancel.
      pendingStart = null;
    } else {
      onJumperCreate?.(pendingStart, holeId);
      pendingStart = null;
    }
  }

  // ---- Keyboard shortcuts ---------------------------------------------
  // 'r' rotates the selected component, 'l' toggles its lock, Delete/
  // Backspace removes the selection. Shortcuts fire only when the canvas
  // (not a child input) has focus. We attach/detach via $effect so the
  // listener is removed when the canvas unmounts.
  $effect(() => {
    function handler(event: KeyboardEvent): void {
      // Don't intercept typing inside form fields.
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

  function onWheel(event: WheelEvent): void {
    event.preventDefault();
    const factor = event.deltaY > 0 ? 1.1 : 1 / 1.1;
    const target = event.currentTarget as SVGSVGElement;
    const rect = target.getBoundingClientRect();
    const pxX = event.clientX - rect.left;
    const pxY = event.clientY - rect.top;
    const worldX = viewX + (pxX / rect.width) * viewW;
    const worldY = viewY + (pxY / rect.height) * viewH;
    viewW *= factor;
    viewH *= factor;
    viewX = worldX - (pxX / rect.width) * viewW;
    viewY = worldY - (pxY / rect.height) * viewH;
  }

  // ---- holeAt (snapping) ----------------------------------------------
  // Plain <script> function (not a $state rune); exposed via Svelte's
  // component instance export. Caller passes clientX/clientY; we return
  // the nearest enabled hole id within a 2.5 mm radius of the snapped
  // world point, else null.
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

  // ---- Render helpers -------------------------------------------------
  const tiePointGroups = $derived(
    board.electricalGroups.filter((g) => g.kind === 'tie-point')
  );

  // Bounding box of a tie-point group's holes, padded by half a pitch so
  // the shading "tucks under" the holes.
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

  // Rail strip geometry: paint a thin rectangle behind each rail line,
  // coloured by the suffix (-plus => red, -minus => dark gray/black).
  interface RailStrip {
    id: string;
    y: number;
    x: number;
    w: number;
    color: 'plus' | 'minus';
  }

  const railStrips = $derived.by((): RailStrip[] => {
    const out: RailStrip[] = [];
    const railGroups = board.electricalGroups.filter((g) => g.kind === 'rail');
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
      out.push({
        id: g.id,
        y: y - board.pitchMm / 2,
        x: minX - board.pitchMm / 2,
        w: maxX - minX + board.pitchMm,
        color: isPlus ? 'plus' : 'minus'
      });
    }
    return out;
  });

  // Hole labelling positions per the spec: columns 1,5,10,...,30 and
  // rows a/j.
  const labelColumns = $derived.by((): number[] => {
    const cols: number[] = [];
    for (let c = 1; c <= board.metadata.columns; c += 1) {
      if (c === 1 || c === 5 || c % 5 === 0) cols.push(c);
    }
    return cols;
  });
  const labelRows = $derived(board.metadata.rows);

  function holeAtGrid(col: number, row: string) {
    return board.holes.find((h) => h.grid.col === col && h.grid.row === row);
  }
</script>
<!--
  This `<svg>` is a custom pannable/zoomable canvas surface (role="application"
  per the standard ARIA pattern for widget-like custom UI, e.g. diagram/CAD
  editors). Svelte's a11y checker does not special-case `application` for SVG
  elements, but the pattern is correct: individual selectable children
  (ComponentLayer/JumperLayer groups) already expose role="button" + tabindex
  + keydown handlers, so keyboard users can reach and activate every
  selectable element without needing the outer canvas itself to be a
  tab-stop or handle key events directly.
-->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<svg
  bind:this={rootEl}
  class="board-canvas"
  viewBox={viewBoxAttr}
  preserveAspectRatio="xMidYMid meet"
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
  onclick={onCanvasClick}
  onwheel={onWheel}
  role="application"
  aria-label="Breadboard editor canvas"
>
  <!-- Tie-point group shading -->
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
          rx="2"
          ry="2"
          fill="rgba(0, 0, 0, 0.04)"
          stroke="rgba(0, 0, 0, 0.06)"
          stroke-width="0.5"
        />
      {/if}
    {/each}
  </g>

  <!-- Rail strips -->
  <g class="rails" aria-hidden="true">
    {#each railStrips as rail (rail.id)}
      {@const tl = toSvgPx({ x: rail.x, y: rail.y })}
      <rect
        x={tl.x}
        y={tl.y}
        width={rail.w * SCALE}
        height={board.pitchMm * SCALE}
        fill={rail.color === 'plus' ? 'var(--color-rail-plus)' : 'var(--color-rail-minus)'}
        opacity="0.85"
      />
    {/each}
  </g>

  <!-- Holes + labels -->
  <HoleLayer
    {board}
    {showLabels}
    {SCALE}
    toSvgPx={toSvgPx}
    labelColumns={labelColumns}
    labelRows={labelRows}
    holeAtGrid={holeAtGrid}
    highlightHoleId={pendingStart}
    jumperToolActive={jumperToolActive}
  />

  <!-- Jumpers (drawn under component bodies so they appear to go behind) -->
  {#if layout}
    <JumperLayer
      jumpers={layout.jumpers}
      {SCALE}
      toSvgPx={toSvgPx}
      selectedId={selectedKind === 'jumper' ? selectedId : null}
      {onSelect}
    />
  {/if}

  <!-- Placements -->
  {#if layout}
    <ComponentLayer
      {board}
      placements={layout.placements}
      {SCALE}
      toSvgPx={toSvgPx}
      selectedId={selectedKind === 'component' ? selectedId : null}
      {onSelect}
      {onPlacementMove}
      {holeAt}
    />
  {/if}
</svg>

<style>
  .board-canvas {
    width: 100%;
    height: 100%;
    min-height: 400px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    display: block;
    touch-action: none;
    cursor: grab;
  }

  .board-canvas:active {
    cursor: grabbing;
  }
</style>