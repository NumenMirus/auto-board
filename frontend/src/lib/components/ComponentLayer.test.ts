import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/svelte';
import ComponentLayer from './ComponentLayer.svelte';
import type { AnyBoardModel, BreadboardModel, Component, ComponentPlacement } from '$lib/types';

// Minimal breadboard model with just enough holes to satisfy the renderer.
const HOLES_PER_ROW = 30;
const ROWS_ABOVE = 5;
const ROWS_BELOW = 25;

function makeBoard(): BreadboardModel {
  const holes: { id: string; point: { x: number; y: number }; row: number; col: number; rail: string | null }[] = [];
  let id = 0;
  for (let r = -ROWS_ABOVE; r < ROWS_BELOW; r += 1) {
    for (let c = 0; c < HOLES_PER_ROW; c += 1) {
      const hid = `h-${r}-${c}`;
      holes.push({ id: hid, point: { x: c * 2.54, y: r * 2.54 }, row: r, col: c, rail: null });
      id += 1;
    }
  }
  return {
    kind: 'breadboard',
    id: 'test-board',
    name: 'Test Board',
    pitchMm: 2.54,
    holes,
    zones: [],
    railStrips: []
  } as unknown as BreadboardModel;
}

const board: AnyBoardModel = makeBoard();

function placementFor(ref: string, holeIds: string[]): ComponentPlacement {
  return {
    componentRef: ref,
    anchorHoleId: holeIds[0] ?? '',
    orientation: 0,
    span: null,
    pinHoles: {},
    occupiedHoleIds: holeIds,
    locked: false
  };
}

function component(ref: string, footprintId: string, value: string | null): Component {
  return { ref, value, footprintId, pins: ['1'], locked: false, tags: [] };
}

const SCALE = 3;
const toSvgPx = (p: { x: number; y: number }): { x: number; y: number } => ({
  x: p.x * SCALE,
  y: p.y * SCALE
});

describe('ComponentLayer shape wiring', () => {
  it('renders a resistor with the part-resistor class when AXIAL-R is in the lookup', () => {
    const placement = placementFor('R1', ['h-1-1', 'h-1-2']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('R1', 'AXIAL-R', '10k')]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-resistor')).toHaveLength(1);
    expect(container.querySelector('g.part-resistor')?.getAttribute('class')).toContain('part-resistor');
  });

  it('renders an IC part for DIP-8 in the lookup', () => {
    const placement = placementFor('U1', [
      'h-2-1', 'h-2-2', 'h-2-3', 'h-2-4',
      'h-3-4', 'h-3-3', 'h-3-2', 'h-3-1'
    ]);
    const lookup = new Map<string, Component>([[placement.componentRef, component('U1', 'DIP-8', 'LM741')]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-ic')).toHaveLength(1);
  });

  it('renders an LED dome for LED-2P and ignores the value hue when value is null', () => {
    const placement = placementFor('D1', ['h-1-5', 'h-1-6']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('D1', 'LED-2P', null)]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-led')).toHaveLength(1);
  });

  it('renders a header strip for HEADER-1x4', () => {
    const placement = placementFor('J1', ['h-2-6', 'h-2-7', 'h-2-8', 'h-2-9']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('J1', 'HEADER-1x4', null)]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-header')).toHaveLength(1);
  });

  it('renders a connector strip with round sockets for CONN-1x3', () => {
    const placement = placementFor('J2', ['h-2-10', 'h-2-11', 'h-2-12']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('J2', 'CONN-1x3', null)]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-connector')).toHaveLength(1);
  });

  it('renders a polar capacitor for ELECTROLYTIC-CAP-2P', () => {
    const placement = placementFor('C1', ['h-1-7', 'h-1-8']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('C1', 'ELECTROLYTIC-CAP-2P', '10uF')]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-capacitor-polar')).toHaveLength(1);
  });

  it('renders a transistor half-moon body for TO-92', () => {
    const placement = placementFor('Q1', ['h-1-9', 'h-1-10', 'h-1-11']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('Q1', 'TO-92', 'BC547')]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    expect(container.querySelectorAll('g.part-transistor')).toHaveLength(1);
  });

  it('falls back to the legacy generic rectangle when no lookup is provided', () => {
    const placement = placementFor('X1', [
      'h-2-1', 'h-2-2', 'h-2-3', 'h-2-4',
      'h-3-4', 'h-3-3', 'h-3-2', 'h-3-1'
    ]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx }
    });
    expect(container.querySelectorAll('g.part-ic')).toHaveLength(0);
    expect(container.querySelectorAll('rect')).toHaveLength(1);
  });

  it('shows the value text on a resistor when the lookup carries a value', () => {
    const placement = placementFor('R1', ['h-1-1', 'h-1-2']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('R1', 'AXIAL-R', '10k')]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    const texts = Array.from(container.querySelectorAll('g.part-resistor text')).map((t) => t.textContent);
    expect(texts).toContain('R1');
    expect(texts).toContain('10k');
  });

  it('skips the value text when the value field is null', () => {
    const placement = placementFor('R1', ['h-1-1', 'h-1-2']);
    const lookup = new Map<string, Component>([[placement.componentRef, component('R1', 'AXIAL-R', null)]]);
    const { container } = render(ComponentLayer, {
      props: { board, placements: [placement], SCALE, toSvgPx, componentLookup: lookup }
    });
    const texts = Array.from(container.querySelectorAll('g.part-resistor text')).map((t) => t.textContent);
    expect(texts).toEqual(['R1']);
  });
});