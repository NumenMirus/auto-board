/**
 * Coordinate transforms between the board's millimetre space and the SVG
 * viewBox pixel space.
 *
 * Convention:
 *   - Board space: x grows right, y grows DOWN. The backend `Point{x,y}`
 *     in millimetres places the top-left hole (row 'a', column 1) at
 *     the origin and the bottom-right hole (row 'j', column 30) at the
 *     positive extreme; the top rail sits at y=-12.70 and the bottom
 *     rail at y=+40.64.
 *   - SVG space: x grows right, y grows DOWN (the SVG spec). Negative
 *     SVG-y is up, positive SVG-y is down.
 *   - Because both spaces share the same handedness, the transform is
 *     a pure scale: `svg = board * scale`. No flip is needed, which is
 *     what makes `boardToSvg` and `svgToBoard` exact inverses and lets
 *     the editor's `viewBox` use board-mm units directly.
 *   - `scale` is the SVG-units-per-millimetre factor used everywhere in
 *     the renderer (the backend SVG renderer uses `width_scale=4.0` so
 *     1 mm == 4 SVG px; tests can use 1.0 for round-trip checks).
 *
 * Both functions are exact inverses — `boardToSvg(svgToBoard(p, s), s) === p`
 * and `svgToBoard(boardToSvg(p, s), s) === p` for any finite point.
 */

export interface Point2D {
  x: number;
  y: number;
}

export function boardToSvg(point: Point2D, scale: number): Point2D {
  return {
    x: point.x * scale,
    y: point.y * scale
  };
}

export function svgToBoard(point: Point2D, scale: number): Point2D {
  return {
    x: point.x / scale,
    y: point.y / scale
  };
}