/**
 * Obstacle-aware orthogonal wire routing for the schematic editor.
 *
 * `SchematicCanvas.svelte` used to draw every connection as a blind 3-segment
 * elbow (`elbowPath` in `./geometry`) with no notion of symbol bodies or other
 * wires, so wires routinely ran straight through component bodies and each
 * other. This module treats every node's drawn extent as a soft obstacle and
 * finds a lattice-constrained orthogonal path between two terminals with an
 * A* search, penalizing (never forbidding) obstacle cells and cells already
 * used by an earlier wire in the same pass.
 */

import type { Point2D } from '../geometry';
import type { Schematic, SchematicNode } from '$lib/types';
import { SHEET_H, SHEET_W, portBounds, symbolBounds, terminalPositions } from './geometry';
import { shapeFor } from './catalog';

export interface RouteRect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

const CLEARANCE = 0.5;
const STEP = 1;
const TURN = 2;
const OBSTACLE = 60;
const WIRE = 8;
const MARGIN = 8;
const MAX_EXPANSIONS = 20000;

const COLS = SHEET_W + 1;
const ROWS = SHEET_H + 1;

function cellIndex(x: number, y: number): number {
  return x + y * COLS;
}

/** Absolute, rotation-aware, clearance-inflated obstacle rect for one node. */
export function nodeObstacle(node: SchematicNode): RouteRect {
  let base: RouteRect;
  if (node.kind === 'symbol') {
    base = symbolBounds(shapeFor(node.footprintId), node.pins);
    // Ref label headroom: always drawn at baseline y = -0.6 with font-size 1.6.
    base = { ...base, minY: Math.min(base.minY, -2.2) };
    if (node.value !== null) {
      const bodyH = base.maxY - base.minY;
      base = { ...base, maxY: Math.max(base.maxY, bodyH + 1.6) };
    }
  } else {
    base = portBounds(node.portKind);
  }

  const theta = (node.rotation * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);
  const corners: Point2D[] = [
    { x: base.minX, y: base.minY },
    { x: base.maxX, y: base.minY },
    { x: base.maxX, y: base.maxY },
    { x: base.minX, y: base.maxY }
  ];
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const c of corners) {
    const rx = c.x * cos - c.y * sin;
    const ry = c.x * sin + c.y * cos;
    if (rx < minX) minX = rx;
    if (rx > maxX) maxX = rx;
    if (ry < minY) minY = ry;
    if (ry > maxY) maxY = ry;
  }

  return {
    minX: minX + node.x - CLEARANCE,
    minY: minY + node.y - CLEARANCE,
    maxX: maxX + node.x + CLEARANCE,
    maxY: maxY + node.y + CLEARANCE
  };
}

function buildBlocked(nodes: readonly SchematicNode[]): Uint8Array {
  const blocked = new Uint8Array(COLS * ROWS);
  for (const node of nodes) {
    const rect = nodeObstacle(node);
    const x0 = Math.max(0, Math.ceil(rect.minX));
    const x1 = Math.min(SHEET_W, Math.floor(rect.maxX));
    const y0 = Math.max(0, Math.ceil(rect.minY));
    const y1 = Math.min(SHEET_H, Math.floor(rect.maxY));
    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        blocked[cellIndex(x, y)] = 1;
      }
    }
  }
  return blocked;
}

const DIRS: readonly Point2D[] = [
  { x: 1, y: 0 },
  { x: -1, y: 0 },
  { x: 0, y: 1 },
  { x: 0, y: -1 }
];

/** Binary min-heap of `(priority, insertionOrder, item)`, insertion order as
 *  tie-break so equal-cost paths resolve deterministically. */
class MinHeap<T> {
  private readonly items: Array<{ priority: number; seq: number; value: T }> = [];
  private seq = 0;

  push(priority: number, value: T): void {
    const entry = { priority, seq: this.seq, value };
    this.seq += 1;
    this.items.push(entry);
    let i = this.items.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (this.isLess(this.items[parent], this.items[i])) break;
      [this.items[parent], this.items[i]] = [this.items[i], this.items[parent]];
      i = parent;
    }
  }

  pop(): T | undefined {
    if (this.items.length === 0) return undefined;
    const top = this.items[0];
    const last = this.items.pop() as { priority: number; seq: number; value: T };
    if (this.items.length > 0) {
      this.items[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = 2 * i + 2;
        let smallest = i;
        if (l < this.items.length && this.isLess(this.items[l], this.items[smallest])) smallest = l;
        if (r < this.items.length && this.isLess(this.items[r], this.items[smallest])) smallest = r;
        if (smallest === i) break;
        [this.items[smallest], this.items[i]] = [this.items[i], this.items[smallest]];
        i = smallest;
      }
    }
    return top.value;
  }

  get size(): number {
    return this.items.length;
  }

  private isLess(
    a: { priority: number; seq: number },
    b: { priority: number; seq: number }
  ): boolean {
    if (a.priority !== b.priority) return a.priority < b.priority;
    return a.seq < b.seq;
  }
}

/** Elbow fallback matching `elbowPath`'s 3-segment shape, as a point list. */
function elbowPoints(a: Point2D, b: Point2D): Point2D[] {
  if (a.x === b.x || a.y === b.y) return [a, b];
  if (Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)) {
    const midX = (a.x + b.x) / 2;
    return [a, { x: midX, y: a.y }, { x: midX, y: b.y }, b];
  }
  const midY = (a.y + b.y) / 2;
  return [a, { x: a.x, y: midY }, { x: b.x, y: midY }, b];
}

function collapseCollinear(points: readonly Point2D[]): Point2D[] {
  if (points.length <= 2) return [...points];
  const out: Point2D[] = [points[0]];
  for (let i = 1; i < points.length - 1; i += 1) {
    const prev = out[out.length - 1];
    const cur = points[i];
    const next = points[i + 1];
    const d1x = cur.x - prev.x;
    const d1y = cur.y - prev.y;
    const d2x = next.x - cur.x;
    const d2y = next.y - cur.y;
    // Same direction (including zero-length segments) => skip the corner.
    const cross = d1x * d2y - d1y * d2x;
    if (cross === 0 && d1x * d2x + d1y * d2y >= 0) continue;
    out.push(cur);
  }
  out.push(points[points.length - 1]);
  return out;
}

/** Orthogonal lattice route between two sheet points in grid units.
 *  `blocked` is the sheet-sized occupancy map from obstacle nodes; `wireUse`
 *  accumulates per-cell usage across a routing pass so later wires avoid
 *  overlapping earlier ones. */
export function routeWire(
  a: Point2D,
  b: Point2D,
  blocked: Uint8Array,
  wireUse: Map<number, number>
): Point2D[] {
  const ax = Math.round(a.x);
  const ay = Math.round(a.y);
  const bx = Math.round(b.x);
  const by = Math.round(b.y);

  if (ax === bx && ay === by) return [a, b];

  const minX = Math.max(0, Math.min(ax, bx) - MARGIN);
  const maxX = Math.min(SHEET_W, Math.max(ax, bx) + MARGIN);
  const minY = Math.max(0, Math.min(ay, by) - MARGIN);
  const maxY = Math.min(SHEET_H, Math.max(ay, by) + MARGIN);

  const startCell = cellIndex(ax, ay);
  const goalCell = cellIndex(bx, by);

  // State id: cell * 5 + dirIndex (4 = "start", no incoming direction yet).
  const stateId = (cell: number, dir: number): number => cell * 5 + dir;

  const gScore = new Map<number, number>();
  const parent = new Map<number, number>();
  const heap = new MinHeap<{ cell: number; dir: number }>();

  const heuristic = (cell: number): number => {
    const x = cell % COLS;
    const y = Math.floor(cell / COLS);
    return Math.abs(x - bx) + Math.abs(y - by);
  };

  const startState = stateId(startCell, 4);
  gScore.set(startState, 0);
  heap.push(heuristic(startCell), { cell: startCell, dir: 4 });

  let expansions = 0;
  let reachedState = -1;

  while (heap.size > 0 && expansions < MAX_EXPANSIONS) {
    const cur = heap.pop();
    if (cur === undefined) break;
    expansions += 1;
    const curState = stateId(cur.cell, cur.dir);
    const curG = gScore.get(curState);
    if (curG === undefined) continue;

    if (cur.cell === goalCell) {
      reachedState = curState;
      break;
    }

    const cx = cur.cell % COLS;
    const cy = Math.floor(cur.cell / COLS);

    for (let d = 0; d < DIRS.length; d += 1) {
      const dir = DIRS[d];
      const nx = cx + dir.x;
      const ny = cy + dir.y;
      if (nx < minX || nx > maxX || ny < minY || ny > maxY) continue;
      const nCell = cellIndex(nx, ny);
      let cost = STEP;
      if (cur.dir !== 4 && cur.dir !== d) cost += TURN;
      if (blocked[nCell] === 1) cost += OBSTACLE;
      if ((wireUse.get(nCell) ?? 0) > 0) cost += WIRE;
      const nState = stateId(nCell, d);
      const tentativeG = curG + cost;
      const existing = gScore.get(nState);
      if (existing === undefined || tentativeG < existing) {
        gScore.set(nState, tentativeG);
        parent.set(nState, curState);
        heap.push(tentativeG + heuristic(nCell), { cell: nCell, dir: d });
      }
    }
  }

  if (reachedState === -1) {
    return elbowPoints(a, b);
  }

  const rawPoints: Point2D[] = [];
  let state: number | undefined = reachedState;
  while (state !== undefined) {
    const cell = Math.floor(state / 5);
    rawPoints.push({ x: cell % COLS, y: Math.floor(cell / COLS) });
    state = parent.get(state);
  }
  rawPoints.reverse();
  rawPoints[0] = a;
  rawPoints[rawPoints.length - 1] = b;

  return collapseCollinear(rawPoints);
}

/** Route every connection in document order; key is the connection's id. */
export function routeSchematic(schematic: Schematic): Map<string, Point2D[]> {
  const blocked = buildBlocked(schematic.nodes);
  const nodeById = new Map(schematic.nodes.map((n) => [n.id, n] as const));
  const wireUse = new Map<number, number>();
  const result = new Map<string, Point2D[]>();

  for (const conn of schematic.connections) {
    const aNode = nodeById.get(conn.a.nodeId);
    const bNode = nodeById.get(conn.b.nodeId);
    if (!aNode || !bNode) continue;
    const aPositions = terminalPositions(aNode);
    const bPositions = terminalPositions(bNode);
    const aKey = conn.a.pin ?? '*';
    const bKey = conn.b.pin ?? '*';
    const aPos = aPositions[aKey];
    const bPos = bPositions[bKey];
    if (!aPos || !bPos) continue;

    const points = routeWire(aPos, bPos, blocked, wireUse);
    result.set(conn.id, points);

    for (let i = 0; i < points.length - 1; i += 1) {
      const from = points[i];
      const to = points[i + 1];
      const steps = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
      const stepX = Math.sign(to.x - from.x);
      const stepY = Math.sign(to.y - from.y);
      for (let s = 0; s <= steps; s += 1) {
        const x = Math.round(from.x + stepX * s);
        const y = Math.round(from.y + stepY * s);
        const idx = cellIndex(Math.max(0, Math.min(SHEET_W, x)), Math.max(0, Math.min(SHEET_H, y)));
        wireUse.set(idx, (wireUse.get(idx) ?? 0) + 1);
      }
    }
  }

  return result;
}

/** `M x y L …` in SVG units, multiplying every grid coordinate by `scale`. */
export function pathFromPoints(points: readonly Point2D[], scale: number): string {
  if (points.length === 0) return '';
  const parts: string[] = [`M ${points[0].x * scale} ${points[0].y * scale}`];
  for (let i = 1; i < points.length; i += 1) {
    parts.push(`L ${points[i].x * scale} ${points[i].y * scale}`);
  }
  return parts.join(' ');
}
