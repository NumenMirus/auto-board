import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/svelte';
import TraceLayer from './TraceLayer.svelte';
import type { Trace } from '$lib/types';

function trace(overrides: Partial<Trace> = {}): Trace {
  return {
    id: 'T1',
    netId: 'GND',
    segments: [
      {
        start: { x: 0, y: 0 },
        end: { x: 2.54, y: 0 },
        layer: 'top',
        widthMm: 0.4
      }
    ],
    vias: [],
    estimatedLengthMm: 12.54,
    widthMm: 0.4,
    locked: false,
    ...overrides
  };
}

describe('TraceLayer', () => {
  it('renders one polyline per segment', () => {
    const traces = [
      trace({
        id: 'T1',
        segments: [
          { start: { x: 0, y: 0 }, end: { x: 2.54, y: 0 }, layer: 'top', widthMm: 0.4 },
          { start: { x: 2.54, y: 0 }, end: { x: 5.08, y: 0 }, layer: 'top', widthMm: 0.4 }
        ]
      })
    ];
    const { container } = render(TraceLayer, {
      props: { traces, SCALE: 4, toSvgPx: (p) => ({ x: p.x * 4, y: p.y * 4 }) }
    });
    expect(container.querySelectorAll('polyline')).toHaveLength(2);
  });

  it('renders a dashed stroke for bottom-layer segments and solid for top', () => {
    const traces = [
      trace({
        id: 'T1',
        segments: [
          { start: { x: 0, y: 0 }, end: { x: 2.54, y: 0 }, layer: 'top', widthMm: 0.4 },
          { start: { x: 2.54, y: 0 }, end: { x: 5.08, y: 0 }, layer: 'bottom', widthMm: 0.4 }
        ]
      })
    ];
    const { container } = render(TraceLayer, {
      props: { traces, SCALE: 4, toSvgPx: (p) => ({ x: p.x * 4, y: p.y * 4 }) }
    });
    const polylines = container.querySelectorAll('polyline');
    expect(polylines[0]?.getAttribute('stroke-dasharray')).toBeNull();
    expect(polylines[1]?.getAttribute('stroke-dasharray')).toBe('2.4 1.6');
  });

  it('assigns a stable colour to the same net id across renders', () => {
    const traces = [trace({ id: 'T1', netId: 'VCC' })];
    const { container: c1 } = render(TraceLayer, {
      props: { traces, SCALE: 4, toSvgPx: (p) => p }
    });
    const { container: c2 } = render(TraceLayer, {
      props: { traces, SCALE: 4, toSvgPx: (p) => p }
    });
    const color1 = c1.querySelector('polyline')?.getAttribute('stroke');
    const color2 = c2.querySelector('polyline')?.getAttribute('stroke');
    expect(color1).toBe(color2);
    expect(color1).toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  it('dims traces that do not match the highlighted net', () => {
    const traces = [trace({ id: 'T1', netId: 'GND' }), trace({ id: 'T2', netId: 'VCC' })];
    const { container } = render(TraceLayer, {
      props: {
        traces,
        SCALE: 4,
        toSvgPx: (p) => p,
        highlightNetId: 'GND'
      }
    });
    const groups = container.querySelectorAll('g.trace');
    expect(groups[0]?.classList.contains('dimmed')).toBe(false);
    expect(groups[1]?.classList.contains('dimmed')).toBe(true);
  });

  it('renders an accent overlay polyline when the trace is selected', () => {
    const traces = [trace({ id: 'T1' })];
    const { container } = render(TraceLayer, {
      props: { traces, SCALE: 4, toSvgPx: (p) => p, selectedId: 'T1' }
    });
    // One base polyline + one accent overlay polyline for the single segment.
    expect(container.querySelectorAll('polyline')).toHaveLength(2);
  });
});
