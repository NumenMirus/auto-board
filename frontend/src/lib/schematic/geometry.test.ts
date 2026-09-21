import { describe, expect, it } from 'vitest';
import { screenToGrid, SCHEMATIC_SCALE } from './geometry';

describe('screenToGrid', () => {
  it('maps an absolute screen point through the CTM into grid units', () => {
    // CTM for an SVG at page offset (54.87, 157.19), uniform scale 0.6309,
    // SCHEMATIC_SCALE = 10 grid units per SVG unit.
    const ctm = { a: 0.6309, b: 0, c: 0, d: 0.6309, e: 54.87, f: 157.19 };
    // Click at CSS (400, 450) — should map to SVG (~547, ~464) → grid (~55, ~46).
    const { x, y } = screenToGrid(400, 450, ctm, SCHEMATIC_SCALE);
    expect(x).toBeCloseTo(54.7, 1);
    expect(y).toBeCloseTo(46.4, 1);
  });

  it('does not double-subtract the SVG box offset (regression for drop shift bug)', () => {
    // Old buggy code passed (clientX - rect.left, clientY - rect.top) to the
    // inverse matrix, double-subtracting the box offset and shifting every drop
    // upward by rect.top / (zoom * SCHEMATIC_SCALE) grid units. Verify the
    // correct call uses absolute coords.
    const ctm = { a: 0.6309, b: 0, c: 0, d: 0.6309, e: 54.87, f: 157.19 };
    // A click at the SVG box's top-left corner (54.87, 157.19) maps to
    // SVG (0, 0) → grid (0, 0). The buggy variant would yield (-87, -249)
    // for the inverse, i.e. far off the sheet.
    const { x, y } = screenToGrid(54.87, 157.19, ctm, SCHEMATIC_SCALE);
    expect(x).toBeCloseTo(0, 6);
    expect(y).toBeCloseTo(0, 6);
  });

  it('returns the origin for a degenerate (zero-determinant) CTM', () => {
    const ctm = { a: 0, b: 0, c: 0, d: 0, e: 0, f: 0 };
    const { x, y } = screenToGrid(100, 200, ctm, SCHEMATIC_SCALE);
    expect(x).toBe(0);
    expect(y).toBe(0);
  });
});
