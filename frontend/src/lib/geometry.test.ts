import { describe, expect, it } from 'vitest';
import { boardToSvg, svgToBoard } from './geometry';

// (a*s)/s and -(-(a*s))/s are exactly `a` only when the multiplication
// has no rounding. We allow up to a few ULPs at the worst case
// (`12.34 * 2.5` rounds to ~30.85 which ` / 2.5` doesn't recover exactly).
const REL_TOL = 1e-12;

function expectClose(a: number, b: number): void {
  const denom = Math.max(1, Math.abs(b));
  expect(Math.abs(a - b) / denom).toBeLessThanOrEqual(REL_TOL);
}

describe('boardToSvg / svgToBoard round-trip', () => {
  const samples = [
    { x: 0, y: 0 },
    { x: 0, y: 27.94 }, // a hole on row j of the half-400 board
    { x: 0, y: -12.7 }, // a top rail hole
    { x: 75.0, y: 17.78 }, // j30
    { x: 12.34, y: -7.89 },
    { x: -1.27, y: 40.64 },
    { x: 1.2345, y: -6.789 } // arbitrary non-integer values
  ];

  for (const p of samples) {
    it(`preserves ${JSON.stringify(p)} through boardToSvg -> svgToBoard`, () => {
      const roundTrip = svgToBoard(boardToSvg(p, 4.0), 4.0);
      expectClose(roundTrip.x, p.x);
      expectClose(roundTrip.y, p.y);
    });
    it(`preserves ${JSON.stringify(p)} through svgToBoard -> boardToSvg`, () => {
      const roundTrip = boardToSvg(svgToBoard(p, 4.0), 4.0);
      expectClose(roundTrip.x, p.x);
      expectClose(roundTrip.y, p.y);
    });
  }
});

describe('boardToSvg', () => {
  it('preserves the sign of x and y (no flip)', () => {
    expect(boardToSvg({ x: 0, y: 5 }, 1)).toEqual({ x: 0, y: 5 });
  });

  it('keeps negative coordinates negative', () => {
    expect(boardToSvg({ x: 7, y: -3 }, 1)).toEqual({ x: 7, y: -3 });
  });
});

describe('svgToBoard', () => {
  it('preserves the sign of x and y (no flip)', () => {
    expect(svgToBoard({ x: 0, y: -5 }, 1)).toEqual({ x: 0, y: -5 });
  });
});

describe('scale', () => {
  it('scales x and y by the same factor', () => {
    expect(boardToSvg({ x: 10, y: 5 }, 2.5)).toEqual({ x: 25, y: 12.5 });
    expect(svgToBoard({ x: 25, y: 12.5 }, 2.5)).toEqual({ x: 10, y: 5 });
  });

  it('handles scale 1 exactly', () => {
    expect(boardToSvg({ x: 3, y: 7 }, 1)).toEqual({ x: 3, y: 7 });
  });
});