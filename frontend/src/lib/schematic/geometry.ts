import type { Point2D } from '../geometry';
import type { SchematicNode } from '$lib/types';
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
