import type { Point2D } from '../geometry';
import type { SchematicNode, SchematicPortKind } from '$lib/types';
import type { SymbolShape } from './catalog';
import { shapeFor } from './catalog';

export const SCHEMATIC_SCALE = 10;
export const SHEET_W = 140;
export const SHEET_H = 90;

export interface SymbolBox {
  w: number;
  h: number;
}

const TWO_PIN_SHAPES = new Set<SymbolShape>([
  'resistor',
  'capacitor',
  'capacitor-polar',
  'diode',
  'led'
]);

/** Terminal offsets in unrotated grid space, keyed by pin name. */
export function terminalOffsets(
  shape: SymbolShape,
  pins: readonly string[]
): Record<string, Point2D> {
  const result: Record<string, Point2D> = {};

  if (TWO_PIN_SHAPES.has(shape)) {
    if (pins.length === 2) {
      result[pins[0]] = { x: 0, y: 0 };
      result[pins[1]] = { x: 6, y: 0 };
    } else {
      for (let k = 0; k < pins.length; k += 1) {
        result[pins[k]] = { x: k * 6, y: 0 };
      }
    }
    return result;
  }

  if (shape === 'transistor') {
    if (pins.length >= 1) result[pins[0]] = { x: 0, y: 0 };
    if (pins.length >= 2) result[pins[1]] = { x: 0, y: 2 };
    if (pins.length >= 3) result[pins[2]] = { x: 0, y: 4 };
    return result;
  }

  if (shape === 'ic') {
    const half = Math.floor(pins.length / 2);
    for (let k = 1; k <= half; k += 1) {
      const leftPin = pins[k - 1];
      const rightPin = pins[pins.length - k];
      result[leftPin] = { x: 0, y: k };
      result[rightPin] = { x: 12, y: k };
    }
    return result;
  }

  if (shape === 'switch') {
    if (pins.length >= 1) result[pins[0]] = { x: 0, y: 0 };
    if (pins.length >= 2) result[pins[1]] = { x: 6, y: 0 };
    if (pins.length >= 3) result[pins[2]] = { x: 0, y: 3 };
    if (pins.length >= 4) result[pins[3]] = { x: 6, y: 3 };
    return result;
  }

  // header, connector, or unknown shape: stack pins vertically along x=0.
  for (let k = 0; k < pins.length; k += 1) {
    result[pins[k]] = { x: 0, y: k };
  }
  return result;
}

/** Bounding box of body + leads in unrotated grid space. */
export function symbolBox(shape: SymbolShape, pins: readonly string[]): SymbolBox {
  if (TWO_PIN_SHAPES.has(shape)) {
    return { w: 6, h: 2 };
  }
  if (shape === 'transistor') {
    return { w: 5, h: 4 };
  }
  if (shape === 'ic') {
    const half = Math.floor(pins.length / 2);
    return { w: 12, h: Math.max(1, half) + 1 };
  }
  if (shape === 'switch') {
    return { w: 6, h: 3 };
  }
  // header, connector, unknown
  return { w: 5, h: Math.max(1, pins.length) };
}

export interface SymbolRect {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** Convert an absolute CSS pointer position to sheet-grid coordinates using
 *  an SVG element's screen CTM. The CTM maps SVG viewBox coords to screen
 *  pixels — including the SVG box's offset from the page origin — so the
 *  inverse must be applied to absolute `(clientX, clientY)`, NOT to a
 *  `(clientX - rect.left, clientY - rect.top)` offset. Subtracting the rect
 *  offset before the inverse double-subtracts the CTM translation and lands
 *  every drop far from the cursor. */
export interface CtmInput {
  a: number;
  b: number;
  c: number;
  d: number;
  e: number;
  f: number;
}

export function screenToGrid(
  clientX: number,
  clientY: number,
  ctm: CtmInput,
  scale: number
): { x: number; y: number } {
  const det = ctm.a * ctm.d - ctm.b * ctm.c;
  if (det === 0) return { x: 0, y: 0 };
  const sxw = (ctm.d * clientX - ctm.c * clientY + (ctm.c * ctm.f - ctm.d * ctm.e)) / det;
  const syw = (-ctm.b * clientX + ctm.a * clientY + (ctm.b * ctm.e - ctm.a * ctm.f)) / det;
  return { x: sxw / scale, y: syw / scale };
}

/** Drawn extents in unrotated grid space (origin = pin-0 terminal).
 *  Values mirror the symbol components in `lib/schematic/symbols/`; keep the
 *  two in sync when a symbol drawing changes. */
export function symbolBounds(shape: SymbolShape, pins: readonly string[]): SymbolRect {
  if (TWO_PIN_SHAPES.has(shape)) return { minX: 0, minY: -2.1, maxX: 6, maxY: 1.3 };
  if (shape === 'transistor') return { minX: 0, minY: 0, maxX: 5, maxY: 4 };
  if (shape === 'ic') {
    const half = Math.max(1, Math.floor(pins.length / 2));
    return { minX: 0, minY: 0.5, maxX: 12, maxY: half + 0.5 };
  }
  if (shape === 'switch') return { minX: 0, minY: 0, maxX: 6, maxY: 3 };
  return { minX: 0, minY: -0.5, maxX: 5, maxY: Math.max(1, pins.length) - 0.5 };
}

/** Drawn extents of a port glyph in grid units (the canvas draws these in
 *  SVG px at `SCHEMATIC_SCALE`; these are those numbers divided by 10).
 *  Must stay in sync with the port glyphs in `lib/components/SchematicCanvas.svelte`. */
export function portBounds(portKind: SchematicPortKind): SymbolRect {
  if (portKind === 'ground') return { minX: -3.2, minY: 0, maxX: 3.2, maxY: 4 };
  if (portKind === 'power') return { minX: -3.2, minY: -5.2, maxX: 3.2, maxY: 0.1 };
  return { minX: -0.3, minY: -1.9, maxX: 3.3, maxY: 0.1 };
}

/** Absolute sheet position of every terminal, rotation applied about the node origin. */
export function terminalPositions(node: SchematicNode): Record<string, Point2D> {
  const baseOffsets: Record<string, Point2D> =
    node.kind === 'symbol'
      ? terminalOffsets(shapeFor(node.footprintId), node.pins)
      : { '*': { x: 0, y: 0 } };

  const theta = (node.rotation * Math.PI) / 180;
  const cos = Math.cos(theta);
  const sin = Math.sin(theta);

  const rotated: Record<string, Point2D> = {};
  for (const [name, p] of Object.entries(baseOffsets)) {
    const rx = p.x * cos - p.y * sin;
    const ry = p.x * sin + p.y * cos;
    rotated[name] = {
      x: round2(rx + node.x),
      y: round2(ry + node.y)
    };
  }
  return rotated;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

/** Orthogonal 3-segment elbow between two sheet points; SVG path in grid units. */
export function elbowPath(a: Point2D, b: Point2D): string {
  if (a.x === b.x || a.y === b.y) {
    return `M ${a.x} ${a.y} L ${b.x} ${b.y}`;
  }
  if (Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)) {
    const midX = (a.x + b.x) / 2;
    return `M ${a.x} ${a.y} H ${midX} V ${b.y} H ${b.x}`;
  }
  const midY = (a.y + b.y) / 2;
  return `M ${a.x} ${a.y} V ${midY} H ${b.x} V ${b.y}`;
}
