import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/svelte';
import ViaLayer from './ViaLayer.svelte';
import type { Via } from '$lib/types';

function via(overrides: Partial<Via> = {}): Via {
  return {
    point: { x: 5.08, y: 2.54 },
    diameterMm: 0.8,
    drillMm: 0.5,
    ...overrides
  };
}

describe('ViaLayer', () => {
  it('renders a ring and a drill circle per via', () => {
    const vias = [via(), via({ point: { x: 10, y: 10 } })];
    const { container } = render(ViaLayer, {
      props: { vias, SCALE: 4, toSvgPx: (p) => ({ x: p.x * 4, y: p.y * 4 }) }
    });
    expect(container.querySelectorAll('circle.via-ring')).toHaveLength(2);
    expect(container.querySelectorAll('circle.via-drill')).toHaveLength(2);
  });

  it('scales the ring and drill radii by diameterMm/drillMm and SCALE', () => {
    const vias = [via({ diameterMm: 1.0, drillMm: 0.4 })];
    const { container } = render(ViaLayer, {
      props: { vias, SCALE: 4, toSvgPx: (p) => ({ x: p.x * 4, y: p.y * 4 }) }
    });
    const ring = container.querySelector('circle.via-ring');
    const drill = container.querySelector('circle.via-drill');
    expect(ring?.getAttribute('r')).toBe(String((1.0 / 2) * 4));
    expect(drill?.getAttribute('r')).toBe(String((0.4 / 2) * 4));
  });

  it('renders nothing when there are no vias', () => {
    const { container } = render(ViaLayer, {
      props: { vias: [], SCALE: 4, toSvgPx: (p) => p }
    });
    expect(container.querySelectorAll('circle')).toHaveLength(0);
  });

  it('positions vias via the toSvgPx transform', () => {
    const vias = [via({ point: { x: 5, y: 10 } })];
    const { container } = render(ViaLayer, {
      props: { vias, SCALE: 4, toSvgPx: (p) => ({ x: p.x * 4, y: p.y * 4 }) }
    });
    const ring = container.querySelector('circle.via-ring');
    expect(ring?.getAttribute('cx')).toBe('20');
    expect(ring?.getAttribute('cy')).toBe('40');
  });
});
