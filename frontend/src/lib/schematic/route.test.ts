import { describe, expect, it } from 'vitest';
import { nodeObstacle, pathFromPoints, routeSchematic, routeWire } from './route';
import type { Schematic } from '$lib/types';

function header(id: string, ref: string, x: number, y: number): Schematic['nodes'][number] {
  return { kind: 'symbol', id, ref, value: null, footprintId: 'HEADER-1x2', pins: ['1', '2'], x, y, rotation: 0 };
}

function dip(id: string, ref: string, x: number, y: number): Schematic['nodes'][number] {
  const pins: string[] = [];
  for (let i = 1; i <= 14; i += 1) pins.push(String(i));
  return { kind: 'symbol', id, ref, value: null, footprintId: 'DIP-14', pins, x, y, rotation: 0 };
}

function conn(id: string, aId: string, bId: string): Schematic['connections'][number] {
  return { id, a: { nodeId: aId, pin: '1' }, b: { nodeId: bId, pin: '1' } };
}

function pointInRect(
  p: { x: number; y: number },
  rect: { minX: number; minY: number; maxX: number; maxY: number }
): boolean {
  return p.x > rect.minX && p.x < rect.maxX && p.y > rect.minY && p.y < rect.maxY;
}

describe('routeSchematic', () => {
  it('routes around an IC body interposed between two header terminals', () => {
    const dipNode = dip('u1', 'U1', 20, 10);
    const schematic: Schematic = {
      version: 1,
      nodes: [header('j1', 'J1', 10, 11), dipNode, header('j2', 'J2', 40, 11)],
      connections: [conn('w1', 'j1', 'j2')],
      netOverrides: []
    };

    const paths = routeSchematic(schematic);
    const points = paths.get('w1');
    expect(points).toBeDefined();
    const obstacle = nodeObstacle(dipNode);
    for (const p of points as { x: number; y: number }[]) {
      expect(pointInRect(p, obstacle)).toBe(false);
    }
  });

  it('returns a straight line when nothing obstructs the terminals', () => {
    const blocked = new Uint8Array(141 * 91);
    const points = routeWire({ x: 10, y: 10 }, { x: 20, y: 10 }, blocked, new Map());
    expect(points).toEqual([
      { x: 10, y: 10 },
      { x: 20, y: 10 }
    ]);
  });

  it('routes two connections in the same corridor onto different tracks', () => {
    const dipA = dip('u1', 'U1', 20, 4);
    const dipB = dip('u2', 'U2', 20, 20);
    const schematic: Schematic = {
      version: 1,
      nodes: [
        header('j1', 'J1', 10, 12),
        header('j2', 'J2', 40, 12),
        header('j3', 'J3', 10, 13),
        header('j4', 'J4', 40, 13),
        dipA,
        dipB
      ],
      connections: [conn('w1', 'j1', 'j2'), conn('w2', 'j3', 'j4')],
      netOverrides: []
    };

    const paths = routeSchematic(schematic);
    const p1 = paths.get('w1');
    const p2 = paths.get('w2');
    expect(p1).toBeDefined();
    expect(p2).toBeDefined();
    expect(p1).not.toEqual(p2);
  });
});

describe('pathFromPoints', () => {
  it('renders a straight two-point polyline as a single M/L pair', () => {
    expect(
      pathFromPoints(
        [
          { x: 1, y: 2 },
          { x: 1, y: 5 }
        ],
        10
      )
    ).toBe('M 10 20 L 10 50');
  });

  it('returns an empty string for no points', () => {
    expect(pathFromPoints([], 10)).toBe('');
  });
});
