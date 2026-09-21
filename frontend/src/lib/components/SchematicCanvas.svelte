<script lang="ts">
  import type {
    Schematic,
    SchematicEndpoint,
    SchematicNode,
    SchematicPortKind
  } from '$lib/types';
  import { deriveNetlist } from '../schematic/netlist';
  import {
    elbowPath,
    terminalPositions,
    SCHEMATIC_SCALE,
    SHEET_W,
    SHEET_H
  } from '../schematic/geometry';
  import { shapeFor } from '../schematic/catalog';
  import SchematicSymbol from './SchematicSymbol.svelte';

  type Props = {
    schematic: Schematic;
    selectedKind?: 'node' | 'connection' | null;
    selectedId?: string | null;
    armedFootprintId?: string | null;
    armedPortKind?: SchematicPortKind | null;
    onSelect?: ((kind: 'node' | 'connection' | null, id: string | null) => void) | undefined;
    onNodeMove?: ((nodeId: string, x: number, y: number) => void) | undefined;
    onNodeRotate?: ((nodeId: string) => void) | undefined;
    onDelete?: ((kind: 'node' | 'connection', id: string) => void) | undefined;
    onConnect?: ((a: SchematicEndpoint, b: SchematicEndpoint) => void) | undefined;
    onPlaceSymbol?: ((footprintId: string, x: number, y: number) => void) | undefined;
    onPlacePort?: ((portKind: SchematicPortKind, x: number, y: number) => void) | undefined;
  };
  let {
    schematic,
    selectedKind = null,
    selectedId = null,
    armedFootprintId = null,
    armedPortKind = null,
    onSelect = undefined,
    onNodeMove = undefined,
    onNodeRotate = undefined,
    onDelete = undefined,
    onConnect = undefined,
    onPlaceSymbol = undefined,
    onPlacePort = undefined
  }: Props = $props();

  // Pure derivation: source of truth for net class lookup used to color
  // connection strokes. Cheap at this size, recomputed on schematic edits.
  const derivedNetlist = $derived.by(() => deriveNetlist(schematic));

  const nodeById = $derived(new Map(schematic.nodes.map((n) => [n.id, n] as const)));

  // Net class per connection: resolves to a wire color. For each net in
  // derived.nets, build a set of every endpoint key it owns (port node id
  // matches the `nodeId` used in connections). Then for each connection,
  // resolve both endpoints to a net and pick a single color: ground wins,
  // then power, otherwise the net's class as resolved by deriveNetlist.
  type ConnClass = 'ground' | 'power' | 'other';

  function endpointKey(ep: SchematicEndpoint): string {
    return `${ep.nodeId}\u0000${ep.pin ?? '*'}`;
  }

  // Map every endpoint key in the schematic to the resolved net name. Built
  // once per derivation so connection rendering is a straight Map lookup.
  const endpointNetName = $derived.by(() => {
    const map = new Map<string, string>();
    // Symbol endpoints: net.pins carries {componentRef, pin}; resolve back
    // to the owning node id via a ref -> node index.
    const refToNodeId = new Map<string, string>();
    for (const n of schematic.nodes) {
      if (n.kind === 'symbol') refToNodeId.set(n.ref, n.id);
    }
    for (const net of derivedNetlist.nets) {
      for (const pin of net.pins) {
        const nodeId = refToNodeId.get(pin.componentRef);
        if (nodeId) {
          map.set(endpointKey({ nodeId, pin: pin.pin }), net.name);
        }
      }
      // A port node owns a net by its own netName; connections touching
      // the port key on '*' resolve here.
      for (const n of schematic.nodes) {
        if (n.kind === 'port' && n.netName === net.name) {
          map.set(endpointKey({ nodeId: n.id, pin: null }), net.name);
        }
      }
    }
    return map;
  });

  const connectionClass = $derived.by(() => {
    const map = new Map<string, ConnClass>();
    for (const conn of schematic.connections) {
      const netName =
        endpointNetName.get(endpointKey(conn.a)) ??
        endpointNetName.get(endpointKey(conn.b));
      if (!netName) {
        map.set(conn.id, 'other');
        continue;
      }
      const net = derivedNetlist.nets.find((n) => n.name === netName);
      const cls = net?.netClass;
      if (cls === 'ground') map.set(conn.id, 'ground');
      else if (cls === 'power') map.set(conn.id, 'power');
      else map.set(conn.id, 'other');
    }
    return map;
  });

  function strokeFor(cls: ConnClass): string {
    if (cls === 'ground') return 'var(--wire-gnd)';
    if (cls === 'power') return 'var(--wire-vcc)';
    return 'var(--ink-2)';
  }

  // ---- Drag state -----------------------------------------------------------
  let draggedNodeId = $state<string | null>(null);
  let dragGrabOffset = $state<{ x: number; y: number } | null>(null);
  let dragStartedAt = $state<{ x: number; y: number } | null>(null);
  let ghostPos = $state<{ x: number; y: number } | null>(null);
  let cursorGrid = $state<{ x: number; y: number } | null>(null);

  // ---- View (pan + zoom) ----------------------------------------------------
  // Content lives inside <g transform="translate(panX,panY) scale(zoom)">.
  // The outer SVG keeps its fixed viewBox so the visible viewport never
  // resizes; only the inner transform changes. This keeps drag-to-move-node
  // and hit-testing math in sheet-grid units — only the visual offset/scale
  // shifts.
  const MIN_ZOOM = 0.4;
  const MAX_ZOOM = 4;
  const ZOOM_STEP = 1.25;
  let panX = $state(0);
  let panY = $state(0);
  let zoom = $state(1);
  // Background pan drag state — separate from node drag so a node drag on a
  // symbol doesn't pan the canvas at the same time.
  let panning = $state(false);
  let panStartClient = $state<{ x: number; y: number } | null>(null);
  let panStartOffset = $state<{ x: number; y: number } | null>(null);

  function clamp(n: number, lo: number, hi: number): number {
    if (n < lo) return lo;
    if (n > hi) return hi;
    return n;
  }

  function resetView(): void {
    panX = 0;
    panY = 0;
    zoom = 1;
  }

  function zoomBy(factor: number, anchorClientX?: number, anchorClientY?: number): void {
    const next = clamp(zoom * factor, MIN_ZOOM, MAX_ZOOM);
    if (next === zoom) return;
    // Zoom around an anchor point (cursor by default) so the world position
    // under the cursor stays put. Derivation: worldPoint = (client - pan) / zoom.
    // New pan = client - worldPoint * next.
    if (anchorClientX !== undefined && anchorClientY !== undefined && rootEl) {
      const rect = rootEl.getBoundingClientRect();
      const localX = anchorClientX - rect.left;
      const localY = anchorClientY - rect.top;
      // current world point under anchor (in svg-coord units, before scale)
      const wx = (localX - panX) / zoom;
      const wy = (localY - panY) / zoom;
      panX = localX - wx * next;
      panY = localY - wy * next;
    } else {
      // Zoom around the centre of the SVG.
      if (rootEl) {
        const rect = rootEl.getBoundingClientRect();
        const cx = rect.width / 2;
        const cy = rect.height / 2;
        const wx = (cx - panX) / zoom;
        const wy = (cy - panY) / zoom;
        panX = cx - wx * next;
        panY = cy - wy * next;
      }
    }
    zoom = next;
  }

  // ---- Wiring state ---------------------------------------------------------
  let pendingEndpoint = $state<SchematicEndpoint | null>(null);

  // ---- Coordinate conversion (mirrors BoardCanvas holeAt shape) ------------
  let rootEl: SVGSVGElement | null = $state(null);

  /**
   * Map a pointer client position to sheet-grid coordinates, accounting for
   * the current pan/zoom transform applied to the inner content group.
   * Uses the SVG element's screen-CTM inverse so the result is correct
   * regardless of how the inner transform changes between events.
   */
  function clientToGrid(clientX: number, clientY: number): { x: number; y: number } {
    const svg = rootEl;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return { x: 0, y: 0 };
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    // Convert local CSS pixels into SVG-world coords (post-pan/zoom) using
    // the inverse of the SVG's current screen CTM. That gives us the point
    // in the inner group's local space — which is exactly SHEET_W * scale
    // units at no zoom, half that at zoom 2×, etc.
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const inverse = ctm.inverse();
    const svgLocalX = inverse.a * localX + inverse.c * localY + inverse.e;
    const svgLocalY = inverse.b * localX + inverse.d * localY + inverse.f;
    // Inner content is in SHEET_W units at scale 1. The inner group's
    // scale is `zoom`, so divide by (zoom * SCHEMATIC_SCALE) to get grid
    // units that `terminalOffsets` / `symbolBox` work in.
    return {
      x: svgLocalX / (zoom * SCHEMATIC_SCALE),
      y: svgLocalY / (zoom * SCHEMATIC_SCALE)
    };
  }

  // ---- Node pointer interactions -------------------------------------------
  function onNodePointerDown(event: PointerEvent, node: SchematicNode): void {
    if (event.button !== 0) return;
    event.stopPropagation();
    onSelect?.('node', node.id);
    draggedNodeId = node.id;
    const start = clientToGrid(event.clientX, event.clientY);
    dragStartedAt = { x: event.clientX, y: event.clientY };
    dragGrabOffset = { x: start.x - node.x, y: start.y - node.y };
    ghostPos = { x: node.x, y: node.y };
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  function onCanvasPointerMove(event: PointerEvent): void {
    const grid = clientToGrid(event.clientX, event.clientY);
    cursorGrid = grid;
    if (panning && panStartClient !== null && panStartOffset !== null) {
      panX = panStartOffset.x + (event.clientX - panStartClient.x);
      panY = panStartOffset.y + (event.clientY - panStartClient.y);
      return;
    }
    if (draggedNodeId !== null && dragGrabOffset !== null) {
      const nx = clamp(grid.x - dragGrabOffset.x, 0, SHEET_W);
      const ny = clamp(grid.y - dragGrabOffset.y, 0, SHEET_H);
      ghostPos = { x: nx, y: ny };
    }
  }

  function onCanvasPointerUp(event: PointerEvent): void {
    if (panning) {
      panning = false;
      panStartClient = null;
      panStartOffset = null;
      (event.currentTarget as Element).releasePointerCapture?.(event.pointerId);
      return;
    }
    if (draggedNodeId === null) return;
    const finalGrid = ghostPos;
    const movedCss =
      dragStartedAt === null
        ? 0
        : Math.hypot(event.clientX - dragStartedAt.x, event.clientY - dragStartedAt.y);
    (event.currentTarget as Element).releasePointerCapture?.(event.pointerId);
    const movedId = draggedNodeId;
    draggedNodeId = null;
    dragGrabOffset = null;
    dragStartedAt = null;
    ghostPos = null;
    if (movedCss >= 3 && finalGrid !== null) {
      onNodeMove?.(movedId, Math.round(finalGrid.x), Math.round(finalGrid.y));
    }
  }

  // ---- Wheel zoom -----------------------------------------------------------
  function onCanvasWheel(event: WheelEvent): void {
    // Trackpad pinch / ctrl+wheel = zoom. Plain wheel scroll over the
    // canvas would otherwise leak into page scroll — preventDefault in both
    // cases so the canvas owns the gesture.
    event.preventDefault();
    const factor = event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    zoomBy(factor, event.clientX, event.clientY);
  }

  // ---- Terminal clicks (wiring) --------------------------------------------
  function onTerminalClick(event: Event, nodeId: string, pin: string): void {
    event.stopPropagation();
    const terminalPin = pin === '*' ? null : pin;
    const incoming: SchematicEndpoint = { nodeId, pin: terminalPin };
    if (pendingEndpoint === null) {
      pendingEndpoint = incoming;
      return;
    }
    if (
      pendingEndpoint.nodeId === incoming.nodeId &&
      pendingEndpoint.pin === incoming.pin
    ) {
      pendingEndpoint = null;
      return;
    }
    onConnect?.(pendingEndpoint, incoming);
    pendingEndpoint = null;
  }

  // Distance threshold (CSS px) above which a pointer-down/up pair is
  // treated as a pan instead of a click. Mirrors the node-drag threshold
  // so single clicks remain crisp.
  const PAN_THRESHOLD_PX = 3;

  function isBackgroundTarget(target: EventTarget | null): boolean {
    if (!target || target === rootEl) return true;
    const el = target as Element;
    return el.getAttribute?.('data-schematic-bg') === '1';
  }

  function onCanvasPointerDown(event: PointerEvent): void {
    // Middle button or primary button on bare background = pan. Primary
    // button on a node/terminal is handled by the per-element handler.
    if (event.button === 1 || (event.button === 0 && isBackgroundTarget(event.target))) {
      event.preventDefault();
      panning = true;
      panStartClient = { x: event.clientX, y: event.clientY };
      panStartOffset = { x: panX, y: panY };
      (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
    }
  }

  function onCanvasClick(event: MouseEvent): void {
    // Suppress the click that fires after a pan drag so the canvas doesn't
    // also clear the selection (or place a symbol) on release.
    if (panStartClient !== null || panning) return;
    if (!isBackgroundTarget(event.target)) return;
    const grid = clientToGrid(event.clientX, event.clientY);
    const x = Math.round(grid.x);
    const y = Math.round(grid.y);
    if (armedFootprintId !== null) {
      onPlaceSymbol?.(armedFootprintId, x, y);
      return;
    }
    if (armedPortKind !== null) {
      onPlacePort?.(armedPortKind, x, y);
      return;
    }
    onSelect?.(null, null);
  }

  function onCanvasDragOver(event: DragEvent): void {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
  }

  function onCanvasDrop(event: DragEvent): void {
    event.preventDefault();
    if (!event.dataTransfer) return;
    const fp = event.dataTransfer.getData('application/x-autoboard-symbol');
    const port = event.dataTransfer.getData('application/x-autoboard-port');
    const grid = clientToGrid(event.clientX, event.clientY);
    const x = Math.round(grid.x);
    const y = Math.round(grid.y);
    if (fp) {
      onPlaceSymbol?.(fp, x, y);
    } else if (port) {
      onPlacePort?.(port as SchematicPortKind, x, y);
    }
  }

  // ---- Keyboard (mirrors BoardCanvas.svelte:109-133 input-guard + teardown) -
  $effect(() => {
    function handler(event: KeyboardEvent): void {
      const t = event.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === 'r' && selectedKind === 'node' && selectedId !== null) {
        event.preventDefault();
        onNodeRotate?.(selectedId);
      } else if (
        (key === 'delete' || key === 'backspace') &&
        selectedKind !== null &&
        selectedId !== null
      ) {
        event.preventDefault();
        onDelete?.(selectedKind, selectedId);
      } else if (key === 'escape') {
        if (pendingEndpoint !== null) pendingEndpoint = null;
      } else if (key === '+' || key === '=') {
        event.preventDefault();
        zoomBy(ZOOM_STEP);
      } else if (key === '-' || key === '_') {
        event.preventDefault();
        zoomBy(1 / ZOOM_STEP);
      } else if (key === '0') {
        event.preventDefault();
        resetView();
      }
    }
    window.addEventListener('keydown', handler);
    return () => {
      window.removeEventListener('keydown', handler);
    };
  });

  // ---- Derived helpers for rendering ---------------------------------------
  const viewBoxW = $derived(SHEET_W * SCHEMATIC_SCALE);
  const viewBoxH = $derived(SHEET_H * SCHEMATIC_SCALE);

  type TerminalEntry = {
    nodeId: string;
    pin: string;
    x: number;
    y: number;
  };

  const terminalEntries = $derived.by(() => {
    const out: TerminalEntry[] = [];
    for (const node of schematic.nodes) {
      const positions = terminalPositions(node);
      for (const [pin, pos] of Object.entries(positions)) {
        out.push({ nodeId: node.id, pin, x: pos.x, y: pos.y });
      }
    }
    return out;
  });

  const pendingAbsPos = $derived.by(() => {
    if (pendingEndpoint === null) return null;
    const n = nodeById.get(pendingEndpoint.nodeId);
    if (!n) return null;
    const positions = terminalPositions(n);
    const key = pendingEndpoint.pin ?? '*';
    return positions[key] ?? null;
  });

  function isSelectedNode(nodeId: string): boolean {
    return selectedKind === 'node' && selectedId === nodeId;
  }

  function isPendingTerminal(nodeId: string, pin: string): boolean {
    if (pendingEndpoint === null) return false;
    if (pendingEndpoint.nodeId !== nodeId) return false;
    const pp = pendingEndpoint.pin ?? '*';
    return pp === pin;
  }

  // Visible position: when dragging, render at the ghost; otherwise at the
  // node's stored position. Lets the renderer stay declarative.
  function renderPos(node: SchematicNode): { x: number; y: number } {
    if (draggedNodeId === node.id && ghostPos !== null) return ghostPos;
    return { x: node.x, y: node.y };
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="schematic-root">
  <svg
    bind:this={rootEl}
    class="schematic-canvas"
    class:dragging={panning}
    viewBox="0 0 {viewBoxW} {viewBoxH}"
    preserveAspectRatio="xMidYMid meet"
    role="application"
    aria-label="Schematic editor canvas"
    onclick={onCanvasClick}
    onpointerdown={onCanvasPointerDown}
    onpointermove={onCanvasPointerMove}
    onpointerup={onCanvasPointerUp}
    onwheel={onCanvasWheel}
    ondragover={onCanvasDragOver}
    ondrop={onCanvasDrop}
  >
    <defs>
      <pattern
        id="schematic-grid"
        width={SCHEMATIC_SCALE}
        height={SCHEMATIC_SCALE}
        patternUnits="userSpaceOnUse"
      >
        <circle
          cx={(SCHEMATIC_SCALE / 2).toFixed(2)}
          cy={(SCHEMATIC_SCALE / 2).toFixed(2)}
          r="0.8"
          fill="var(--paper-4)"
        />
      </pattern>
    </defs>

    <!-- Everything inside the SVG lives in sheet-grid space; the inner
         <g class="sheet"> applies the pan/zoom transform so the SVG
         viewBox itself never needs to change. -->
    <g class="sheet" transform="translate({panX} {panY}) scale({zoom})">
      <!-- Sheet background: paper, then dot grid. Both live inside the
           transform group so they pan/zoom with the rest of the content.
           The dot rect carries data-schematic-bg so canvas-level click
           handlers can recognise a bare-background hit and dispatch
           click-to-place / clear-selection. -->
      <rect
        data-schematic-bg="1"
        x="0"
        y="0"
        width={viewBoxW}
        height={viewBoxH}
        fill="var(--paper-0)"
      />
      <rect
        data-schematic-bg="1"
        x="0"
        y="0"
        width={viewBoxW}
        height={viewBoxH}
        fill="url(#schematic-grid)"
        pointer-events="none"
      />


  <!-- Connections first so nodes paint over them at shared terminals. -->
  <g class="connections">
    {#each schematic.connections as conn (conn.id)}
      {@const aNode = nodeById.get(conn.a.nodeId)}
      {@const bNode = nodeById.get(conn.b.nodeId)}
      {#if aNode && bNode}
        {@const aPositions = terminalPositions(aNode)}
        {@const bPositions = terminalPositions(bNode)}
        {@const aKey = conn.a.pin ?? '*'}
        {@const bKey = conn.b.pin ?? '*'}
        {@const aPos = aPositions[aKey]}
        {@const bPos = bPositions[bKey]}
        {#if aPos && bPos}
          {@const ax = aPos.x * SCHEMATIC_SCALE}
          {@const ay = aPos.y * SCHEMATIC_SCALE}
          {@const bx = bPos.x * SCHEMATIC_SCALE}
          {@const by = bPos.y * SCHEMATIC_SCALE}
          {@const cls = connectionClass.get(conn.id) ?? 'other'}
          {@const isSelected = selectedKind === 'connection' && selectedId === conn.id}
          <path
            d={elbowPath({ x: ax, y: ay }, { x: bx, y: by })}
            fill="none"
            stroke={strokeFor(cls)}
            stroke-width={isSelected ? 2.4 : 1.6}
            data-connection-id={conn.id}
          />
          <path
            d={elbowPath({ x: ax, y: ay }, { x: bx, y: by })}
            fill="none"
            stroke="transparent"
            stroke-width="8"
            pointer-events="stroke"
            role="button"
            tabindex="0"
            aria-label={`Connection ${conn.id}`}
            aria-pressed={isSelected}
            onclick={(e) => {
              e.stopPropagation();
              onSelect?.('connection', conn.id);
            }}
            onkeydown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                e.stopPropagation();
                onSelect?.('connection', conn.id);
              }
            }}
          />
        {/if}
      {/if}
    {/each}
  </g>

  <!-- Pending-wire rubber band. -->
  {#if pendingEndpoint !== null && pendingAbsPos !== null && cursorGrid !== null}
    {@const px = pendingAbsPos.x * SCHEMATIC_SCALE}
    {@const py = pendingAbsPos.y * SCHEMATIC_SCALE}
    {@const cx = cursorGrid.x * SCHEMATIC_SCALE}
    {@const cy = cursorGrid.y * SCHEMATIC_SCALE}
    <path
      d={elbowPath({ x: px, y: py }, { x: cx, y: cy })}
      fill="none"
      stroke="var(--accent-1)"
      stroke-width="1.6"
      stroke-dasharray="3 3"
      pointer-events="none"
    />
  {/if}

  <!-- Nodes -->
  <g class="nodes">
    {#each schematic.nodes as node (node.id)}
      {@const pos = renderPos(node)}
      {@const selected = isSelectedNode(node.id)}
      <g
        class="schematic-node"
        class:selected
        class:dragging={draggedNodeId === node.id}
        transform="translate({pos.x * SCHEMATIC_SCALE},{pos.y * SCHEMATIC_SCALE}) rotate({node.rotation})"
        role="button"
        tabindex="0"
        aria-label={`Schematic node ${node.kind === 'symbol' ? node.ref : node.netName}`}
        aria-pressed={selected}
        onpointerdown={(e) => onNodePointerDown(e, node)}
        onclick={(e) => {
          e.stopPropagation();
          onSelect?.('node', node.id);
        }}
        onkeydown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            e.stopPropagation();
            onSelect?.('node', node.id);
          }
        }}
        data-node-id={node.id}
      >
        {#if node.kind === 'symbol'}
          <g transform="scale({SCHEMATIC_SCALE})">
            <SchematicSymbol
              shape={shapeFor(node.footprintId)}
              pins={node.pins}
              label={node.ref}
              value={node.value}
              selected={selected}
              showPinNames
            />
          </g>
        {:else if node.portKind === 'ground'}
          <g class="port port-ground" stroke={selected ? 'var(--accent-1)' : 'var(--wire-gnd)'}>
            <line x1="0" y1="0" x2="0" y2={SCHEMATIC_SCALE * 1} stroke-width="1.6" />
            <line x1="-1.6" y1={SCHEMATIC_SCALE * 1} x2="1.6" y2={SCHEMATIC_SCALE * 1} stroke-width="1.6" />
            <line x1="-1" y1={SCHEMATIC_SCALE * 1.4} x2="1" y2={SCHEMATIC_SCALE * 1.4} stroke-width="1.6" />
            <line x1="-0.5" y1={SCHEMATIC_SCALE * 1.8} x2="0.5" y2={SCHEMATIC_SCALE * 1.8} stroke-width="1.6" />
          </g>
        {:else if node.portKind === 'power'}
          <g class="port port-power" stroke={selected ? 'var(--accent-1)' : 'var(--wire-vcc)'}>
            <text
              x="0"
              y={-SCHEMATIC_SCALE * 0.4}
              text-anchor="middle"
              font-family="var(--font-mono)"
              font-size={SCHEMATIC_SCALE * 0.9}
              fill="var(--ink-3)"
              stroke="none"
            >{node.netName}</text>
            <line x1="0" y1="0" x2="0" y2={-SCHEMATIC_SCALE * 1} stroke-width="1.6" />
            <line x1="-1.6" y1={-SCHEMATIC_SCALE * 1} x2="1.6" y2={-SCHEMATIC_SCALE * 1} stroke-width="1.6" />
          </g>
        {:else}
          <g class="port port-label" stroke={selected ? 'var(--accent-1)' : 'var(--ink-2)'}>
            <line x1="0" y1="0" x2="0" y2={-SCHEMATIC_SCALE * 1} stroke-width="1.6" />
            <rect
              x={SCHEMATIC_SCALE * 0.2}
              y={-SCHEMATIC_SCALE * 1.8}
              width={SCHEMATIC_SCALE * 3}
              height={SCHEMATIC_SCALE * 1}
              fill="var(--paper-1)"
              stroke-width="1"
              rx="2"
              ry="2"
            />
            <text
              x={SCHEMATIC_SCALE * 1.7}
              y={-SCHEMATIC_SCALE * 1.05}
              text-anchor="middle"
              dominant-baseline="middle"
              font-family="var(--font-mono)"
              font-size={SCHEMATIC_SCALE * 0.9}
              fill="var(--ink-2)"
              stroke="none"
            >{node.netName}</text>
          </g>
        {/if}
      </g>
    {/each}
  </g>

  <!-- Terminal hit targets: rendered last so they win hit-testing. Sits
       outside the per-node rotated group because terminalPositions already
       returns absolute sheet coords, and we want pointer events to land
       on the dot regardless of the node's orientation. -->
  <g class="terminals">
    {#each terminalEntries as t (t.nodeId + '\u0000' + t.pin)}
      {@const px = t.x * SCHEMATIC_SCALE}
      {@const py = t.y * SCHEMATIC_SCALE}
      {@const active = isPendingTerminal(t.nodeId, t.pin)}
      <circle
        cx={px.toFixed(2)}
        cy={py.toFixed(2)}
        r="6"
        fill="transparent"
        pointer-events="all"
        role="button"
        tabindex="0"
        aria-label={`Pin ${t.pin} of ${t.nodeId}`}
        data-node-id={t.nodeId}
        data-pin={t.pin}
        onclick={(e) => onTerminalClick(e, t.nodeId, t.pin)}
        onkeydown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onTerminalClick(e, t.nodeId, t.pin);
          }
        }}
      />
      <circle
        cx={px.toFixed(2)}
        cy={py.toFixed(2)}
        r="1.8"
        fill={active ? 'var(--accent-1)' : 'var(--ink-3)'}
        pointer-events="none"
      />
    {/each}
    </g>
    </g>
  </svg>

  <div class="zoom-controls" role="group" aria-label="Schematic view controls">
    <button
      type="button"
      class="zoom-btn"
      aria-label="Zoom out"
      title="Zoom out (-)"
      onclick={() => zoomBy(1 / ZOOM_STEP)}
    >−</button>
    <button
      type="button"
      class="zoom-btn"
      aria-label="Reset view"
      title="Reset view (0)"
      onclick={resetView}
    >{Math.round(zoom * 100)}%</button>
    <button
      type="button"
      class="zoom-btn"
      aria-label="Zoom in"
      title="Zoom in (+)"
      onclick={() => zoomBy(ZOOM_STEP)}
    >+</button>
  </div>
</div>

<style>
  .schematic-root {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
  }

  .schematic-canvas {
    width: 100%;
    height: 100%;
    display: block;
    user-select: none;
    background: var(--paper-0);
    border-radius: var(--r-2);
    touch-action: none;
  }

  .schematic-canvas:focus {
    outline: none;
  }

  .schematic-canvas.dragging {
    cursor: grabbing;
  }

  .zoom-controls {
    position: absolute;
    top: var(--sp-2);
    right: var(--sp-2);
    display: inline-flex;
    align-items: stretch;
    background: var(--paper-0);
    border: 1px solid var(--paper-edge);
    border-radius: var(--r-2);
    box-shadow: var(--sh-1);
    overflow: hidden;
    z-index: 1;
  }

  .zoom-btn {
    padding: 4px 10px;
    font-size: var(--fs-12);
    font-family: var(--font-mono);
    color: var(--ink-2);
    background: var(--paper-0);
    border: none;
    border-radius: 0;
    line-height: 1.2;
  }

  .zoom-btn + .zoom-btn {
    border-left: 1px solid var(--paper-edge);
  }

  .zoom-btn:hover:not(:disabled) {
    background: var(--paper-2);
    border-color: transparent;
  }

  .zoom-btn:active:not(:disabled) {
    background: var(--paper-3);
  }

  .zoom-btn:focus-visible {
    outline: 2px solid var(--accent-1);
    outline-offset: -2px;
  }

  .schematic-canvas:focus {
    outline: none;
  }

  .terminals circle {
    cursor: crosshair;
  }

  .schematic-node {
    cursor: grab;
  }

  .schematic-node.dragging {
    cursor: grabbing;
  }

  .port text {
    user-select: none;
    pointer-events: none;
  }
</style>
