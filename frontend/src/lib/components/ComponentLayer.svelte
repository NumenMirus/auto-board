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
    // Provided by BoardCanvas so we can snap the ghost to the nearest hole
    // during a drag. Receives client (screen) coords.
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

  // The solver's `occupiedHoleIds` are the canonical post-rotation
  // lattice cells the body covers, so we visit each and draw a soft
  // rectangle around the union.
  const holeById = $derived(new Map(board.holes.map((h) => [h.id, h])));

  function cellsForPlacement(p: ComponentPlacement): Array<{ x: number; y: number }> {
    const out: Array<{ x: number; y: number }> = [];
    for (const hid of p.occupiedHoleIds) {
      const h = holeById.get(hid);
      if (h) out.push({ x: h.point.x, y: h.point.y });
    }
    return out;
  }

  // ---- Drag machinery --------------------------------------------------
  // Only one component is dragged at a time. The pointer-capture pattern
  // means we don't have to track mousemove on the document — the SVG keeps
  // firing move events until the user releases. We render a "ghost" rect
  // (semi-transparent) at the snapped target location so the user sees
  // where the part will land.
  let dragRef = $state<string | null>(null);
  let dragGhostHoleId = $state<string | null>(null);
  let ghostOffset = $state<{ x: number; y: number } | null>(null);

  function onComponentPointerDown(
    event: PointerEvent,
    placement: ComponentPlacement
  ): void {
    // Don't initiate a drag from a locked part — clicking it still
    // selects it, but it can't be moved.
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
      {@const widthMm = maxX - minX + 2.54}
      {@const heightMm = maxY - minY + 2.54}
      {@const isDragging = dragRef === placement.componentRef}
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
        <rect
          x={tl.x}
          y={tl.y}
          width={widthMm * SCALE}
          height={heightMm * SCALE}
          fill={placement.locked ? '#e5e7eb' : '#fde68a'}
          fill-opacity={isDragging ? 0.3 : 0.7}
          stroke={isSelected ? 'var(--color-accent)' : '#b45309'}
          stroke-width={isSelected ? 0.8 * SCALE : 0.3 * SCALE}
          rx="1"
          ry="1"
        />
        <text
          x={tl.x + (widthMm * SCALE) / 2}
          y={tl.y + (heightMm * SCALE) / 2}
          text-anchor="middle"
          dominant-baseline="middle"
          font-size={Math.min(widthMm, heightMm) * SCALE * 0.6}
          font-weight="600"
          fill="var(--color-fg)"
        >
          {placement.componentRef}
        </text>
      </g>
      {#if isDragging}
        {@const ghostTL = ghostCenter()}
        {#if ghostTL}
          {@const ghostSvg = toSvgPx({ x: ghostTL.x - 1.27, y: ghostTL.y - 1.27 })}
          <rect
            class="drag-ghost"
            x={ghostSvg.x}
            y={ghostSvg.y}
            width={widthMm * SCALE}
            height={heightMm * SCALE}
            fill="rgba(31, 111, 235, 0.25)"
            stroke="var(--color-accent)"
            stroke-width={0.6 * SCALE}
            stroke-dasharray={`${2 * SCALE} ${1.5 * SCALE}`}
            rx="1"
            ry="1"
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

  .drag-ghost {
    pointer-events: none;
  }

  text {
    user-select: none;
    pointer-events: none;
  }
</style>