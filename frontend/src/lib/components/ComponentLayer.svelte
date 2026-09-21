<script lang="ts">
  import type { AnyBoardModel, ComponentPlacement } from '../types';
  import type { Point2D } from '../geometry';

  type Props = {
    board: AnyBoardModel;
    placements: ComponentPlacement[];
    SCALE: number;
    toSvgPx: (p: Point2D) => Point2D;
    selectedId?: string | null;
    onSelect?: ((kind: 'component' | 'jumper' | 'trace', id: string) => void) | undefined;
    onPlacementMove?: ((componentRef: string, newAnchorHoleId: string) => void) | undefined;
    holeAt?: ((clientX: number, clientY: number) => string | null) | undefined;
  };
  let {
    board,
    placements,
    SCALE,
    toSvgPx,
    selectedId = null,
    onSelect = undefined,
    onPlacementMove = undefined,
    holeAt = undefined
  }: Props = $props();

  const holeById = $derived(new Map(board.holes.map((h) => [h.id, h])));

  function cellsForPlacement(p: ComponentPlacement): Array<{ x: number; y: number }> {
    const out: Array<{ x: number; y: number }> = [];
    for (const hid of p.occupiedHoleIds) {
      const h = holeById.get(hid);
      if (h) out.push({ x: h.point.x, y: h.point.y });
    }
    return out;
  }

  // Heuristic shape classification based on how many lattice cells the
  // placement covers — good enough to draw ICs as ICs, passives as
  // passives, even though the exact footprint comes from the catalog.
  type Shape = 'dip' | 'axial' | 'radial' | 'switch' | 'header';
  function shapeOf(p: ComponentPlacement): Shape {
    const n = p.occupiedHoleIds.length;
    if (n === 0) return 'radial';
    // Determine footprint by ref heuristic: TACT-* and SW-* are switches;
    // headers are 1×N; DIP-* are ICs; everything 2-cell horizontal or
    // vertical is axial/radial.
    const ref = p.componentRef;
    if (/^SW|^TACT/i.test(ref)) return 'switch';
    if (/^H\d|^J\d|^CONN/i.test(ref) && n <= 6) return 'header';
    if (n >= 6) return 'dip';
    if (n === 2) {
      const cells = cellsForPlacement(p);
      if (cells.length === 2) {
        const [a, b] = cells;
        return a.x === b.x || a.y === b.y ? 'axial' : 'radial';
      }
    }
    return 'header';
  }

  let dragRef = $state<string | null>(null);
  let dragGhostHoleId = $state<string | null>(null);
  let ghostOffset = $state<{ x: number; y: number } | null>(null);

  function onComponentPointerDown(
    event: PointerEvent,
    placement: ComponentPlacement
  ): void {
    if (placement.locked) {
      onSelect?.('component', placement.componentRef);
      return;
    }
    if (event.button !== 0) return;
    event.stopPropagation();
    onSelect?.('component', placement.componentRef);
    dragRef = placement.componentRef;
    const cells = cellsForPlacement(placement);
    const anchor = holeById.get(placement.anchorHoleId);
    if (cells.length === 0 || !anchor) return;
    const minX = Math.min(...cells.map((c) => c.x));
    const minY = Math.min(...cells.map((c) => c.y));
    ghostOffset = { x: anchor.point.x - minX, y: anchor.point.y - minY };
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  }

  function onComponentPointerMove(event: PointerEvent): void {
    if (dragRef === null || holeAt === undefined) return;
    dragGhostHoleId = holeAt(event.clientX, event.clientY);
  }

  function onComponentPointerUp(event: PointerEvent, placement: ComponentPlacement): void {
    if (dragRef !== placement.componentRef) return;
    const finalHole = dragGhostHoleId;
    (event.currentTarget as Element).releasePointerCapture?.(event.pointerId);
    dragRef = null;
    dragGhostHoleId = null;
    ghostOffset = null;
    if (finalHole !== null && finalHole !== placement.anchorHoleId) {
      onPlacementMove?.(placement.componentRef, finalHole);
    }
  }

  function ghostCenter(): { x: number; y: number } | null {
    if (ghostOffset === null) return null;
    const target = holeById.get(dragGhostHoleId ?? '');
    if (!target) return null;
    return { x: target.point.x + ghostOffset.x, y: target.point.y + ghostOffset.y };
  }

  // Pin-1 indicator: a small notch on the lower-left of a DIP body's
  // rendered rectangle. Computed in SVG space.
  function dipNotch(minX: number, minY: number, maxX: number, maxY: number): string {
    const notchR = Math.min(maxX - minX, maxY - minY) * 0.12;
    const x = minX + (maxX - minX) * 0.18;
    const y = minY + (maxY - minY) * 0.18;
    return `M ${(x + notchR).toFixed(2)} ${y.toFixed(2)} A ${notchR.toFixed(2)} ${notchR.toFixed(2)} 0 0 0 ${x.toFixed(2)} ${(y + notchR).toFixed(2)}`;
  }
</script>

<g class="components">
  {#each placements as placement (placement.componentRef)}
    {@const cells = cellsForPlacement(placement)}
    {@const isSelected = selectedId === placement.componentRef}
    {#if cells.length > 0}
      {@const minX = Math.min(...cells.map((c) => c.x))}
      {@const maxX = Math.max(...cells.map((c) => c.x))}
      {@const minY = Math.min(...cells.map((c) => c.y))}
      {@const maxY = Math.max(...cells.map((c) => c.y))}
      {@const tl = toSvgPx({ x: minX - 1.27, y: minY - 1.27 })}
      {@const br = toSvgPx({ x: maxX + 1.27, y: maxY + 1.27 })}
      {@const widthMm = maxX - minX + 2.54}
      {@const heightMm = maxY - minY + 2.54}
      {@const isDragging = dragRef === placement.componentRef}
      {@const shape = shapeOf(placement)}
      <g
        class="component"
        class:selected={isSelected}
        class:locked={placement.locked}
        class:dragging={isDragging}
        data-component-ref={placement.componentRef}
        role="button"
        tabindex="0"
        aria-label={`Component ${placement.componentRef}`}
        aria-pressed={isSelected}
        onpointerdown={(e) => onComponentPointerDown(e, placement)}
        onpointermove={onComponentPointerMove}
        onpointerup={(e) => onComponentPointerUp(e, placement)}
        onclick={(e) => {
          e.stopPropagation();
          onSelect?.('component', placement.componentRef);
        }}
        onkeydown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            e.stopPropagation();
            onSelect?.('component', placement.componentRef);
          }
        }}
      >
        {#if shape === 'dip'}
          <!-- IC body: dark plastic with pin-1 notch. -->
          <rect
            x={tl.x}
            y={tl.y}
            width={(maxX - minX + 2.54) * SCALE}
            height={(maxY - minY + 2.54) * SCALE}
            rx="1.0"
            ry="1.0"
            fill={isDragging ? '#8A8273' : '#5C564B'}
            fill-opacity={isDragging ? 0.45 : 1}
            stroke={isSelected ? 'var(--accent-1)' : '#3F3A32'}
            stroke-width={isSelected ? 0.6 * SCALE : 0.2 * SCALE}
          />
          <path
            d={dipNotch(tl.x, tl.y, br.x, br.y)}
            fill="none"
            stroke="rgba(245,242,235,0.7)"
            stroke-width={0.25 * SCALE}
          />
          <text
            x={tl.x + ((maxX - minX + 2.54) * SCALE) / 2}
            y={tl.y + ((maxY - minY + 2.54) * SCALE) / 2 - 0.2 * SCALE}
            text-anchor="middle"
            dominant-baseline="middle"
            font-family="'JetBrains Mono', monospace"
            font-size={Math.min(widthMm, heightMm) * SCALE * 0.22}
            font-weight="500"
            fill="#F5F2EB"
          >
            {placement.componentRef}
          </text>
        {:else if shape === 'axial'}
          <!-- Axial passive: thin pill body aligned with the wire span. -->
          {@const ax = cells[0]}
          {@const bx = cells[1]}
          {@const axSvg = toSvgPx(ax)}
          {@const bxSvg = toSvgPx(bx)}
          {@const midX = (axSvg.x + bxSvg.x) / 2}
          {@const midY = (axSvg.y + bxSvg.y) / 2}
          {@const lengthPx = Math.hypot(bxSvg.x - axSvg.x, bxSvg.y - axSvg.y)}
          {@const angleDeg =
            (Math.atan2(bxSvg.y - axSvg.y, bxSvg.x - axSvg.x) * 180) / Math.PI}
          <g transform={`translate(${midX} ${midY}) rotate(${angleDeg})`}>
            <rect
              x={-lengthPx / 2 + 1.2 * SCALE}
              y={-0.85 * SCALE}
              width={lengthPx - 2.4 * SCALE}
              height={1.7 * SCALE}
              rx="0.85"
              ry="0.85"
              fill={placement.locked ? '#D8D2C2' : '#C9BC95'}
              stroke={isSelected ? 'var(--accent-1)' : '#7E6A3C'}
              stroke-width={isSelected ? 0.5 * SCALE : 0.18 * SCALE}
              opacity={isDragging ? 0.45 : 1}
            />
            <line
              x1={-lengthPx / 2}
              x2={-lengthPx / 2 + 1.2 * SCALE}
              y1="0"
              y2="0"
              stroke="#B5AE9F"
              stroke-width="0.3"
            />
            <line
              x1={lengthPx / 2 - 1.2 * SCALE}
              x2={lengthPx / 2}
              y1="0"
              y2="0"
              stroke="#B5AE9F"
              stroke-width="0.3"
            />
            <text
              x="0"
              y={-0.3 * SCALE}
              text-anchor="middle"
              dominant-baseline="middle"
              font-family="'JetBrains Mono', monospace"
              font-size={Math.max(2.0, lengthPx * 0.14)}
              font-weight="500"
              fill="#3A2F12"
            >
              {placement.componentRef}
            </text>
          </g>
        {:else if shape === 'radial'}
          <!-- Radial: a small disc with two leads fanning out. -->
          {@const ax = cells[0]}
          {@const bx = cells[1]}
          {@const axSvg = toSvgPx(ax)}
          {@const bxSvg = toSvgPx(bx)}
          {@const midX = (axSvg.x + bxSvg.x) / 2}
          {@const midY = (axSvg.y + bxSvg.y) / 2}
          <g transform={`translate(${midX} ${midY})`}>
            <circle
              r={2.0 * SCALE}
              fill={placement.locked ? '#E2DBCB' : '#A8B8C8'}
              stroke={isSelected ? 'var(--accent-1)' : '#5A7186'}
              stroke-width={isSelected ? 0.5 * SCALE : 0.2 * SCALE}
              opacity={isDragging ? 0.45 : 1}
            />
            <text
              x="0"
              y="0.3"
              text-anchor="middle"
              dominant-baseline="middle"
              font-family="'JetBrains Mono', monospace"
              font-size="2.0"
              font-weight="500"
              fill="#1F2D38"
            >
              {placement.componentRef}
            </text>
          </g>
        {:else if shape === 'switch'}
          <!-- Tactile switch: square body, two pairs of pins underneath. -->
          <rect
            x={tl.x}
            y={tl.y}
            width={(maxX - minX + 2.54) * SCALE}
            height={(maxY - minY + 2.54) * SCALE}
            rx="0.4"
            ry="0.4"
            fill={placement.locked ? '#D8D2C2' : '#5C564B'}
            fill-opacity={isDragging ? 0.45 : 1}
            stroke={isSelected ? 'var(--accent-1)' : '#3F3A32'}
            stroke-width={isSelected ? 0.5 * SCALE : 0.2 * SCALE}
          />
          <text
            x={tl.x + ((maxX - minX + 2.54) * SCALE) / 2}
            y={tl.y + ((maxY - minY + 2.54) * SCALE) / 2}
            text-anchor="middle"
            dominant-baseline="middle"
            font-family="'JetBrains Mono', monospace"
            font-size={Math.min(widthMm, heightMm) * SCALE * 0.24}
            font-weight="500"
            fill="#F0EDE3"
          >
            {placement.componentRef}
          </text>
        {:else}
          <!-- Header / connector: muted block. -->
          <rect
            x={tl.x}
            y={tl.y}
            width={(maxX - minX + 2.54) * SCALE}
            height={(maxY - minY + 2.54) * SCALE}
            rx="0.4"
            ry="0.4"
            fill={placement.locked ? '#D8D2C2' : '#6E6453'}
            fill-opacity={isDragging ? 0.45 : 1}
            stroke={isSelected ? 'var(--accent-1)' : '#3F3A32'}
            stroke-width={isSelected ? 0.5 * SCALE : 0.2 * SCALE}
          />
          <text
            x={tl.x + ((maxX - minX + 2.54) * SCALE) / 2}
            y={tl.y + ((maxY - minY + 2.54) * SCALE) / 2}
            text-anchor="middle"
            dominant-baseline="middle"
            font-family="'JetBrains Mono', monospace"
            font-size={Math.min(widthMm, heightMm) * SCALE * 0.26}
            font-weight="500"
            fill="#F5F2EB"
          >
            {placement.componentRef}
          </text>
        {/if}

        {#if placement.locked}
          <!-- Locked badge -->
          <g
            transform={`translate(${br.x - 1.2 * SCALE} ${tl.y - 0.2 * SCALE})`}
            pointer-events="none"
          >
            <rect
              x={-1.2 * SCALE}
              y={-1.2 * SCALE}
              width={2.4 * SCALE}
              height={2.4 * SCALE}
              rx="0.3"
              ry="0.3"
              fill="var(--paper-0)"
              stroke="#A8A294"
              stroke-width="0.2"
            />
            <text
              x="0"
              y="0.15"
              text-anchor="middle"
              dominant-baseline="middle"
              font-family="'JetBrains Mono', monospace"
              font-size="2.0"
              font-weight="600"
              fill="#3A332B"
            >
              L
            </text>
          </g>
        {/if}
      </g>

      {#if isDragging}
        {@const ghostTL = ghostCenter()}
        {#if ghostTL}
          {@const ghostSvg = toSvgPx({ x: ghostTL.x - 1.27, y: ghostTL.y - 1.27 })}
          <rect
            class="drag-ghost"
            x={ghostSvg.x}
            y={ghostSvg.y}
            width={(maxX - minX + 2.54) * SCALE}
            height={(maxY - minY + 2.54) * SCALE}
            rx="1.2"
            ry="1.2"
            fill="var(--accent-1)"
            fill-opacity="0.12"
            stroke="var(--accent-1)"
            stroke-width="0.4"
            stroke-dasharray="1.6 1.6"
            pointer-events="none"
          />
        {/if}
      {/if}
    {/if}
  {/each}
</g>

<style>
  .components {
    shape-rendering: geometricPrecision;
  }

  .component {
    cursor: grab;
  }

  .component.dragging {
    cursor: grabbing;
  }

  .component.locked {
    cursor: default;
  }

  .component.selected {
    cursor: grab;
  }

  text {
    user-select: none;
    pointer-events: none;
  }
</style>