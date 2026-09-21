import { describe, expect, it } from 'vitest';
import { deriveNetlist, pruneLayout } from './netlist';
import type {
  ComponentPlacement,
  Jumper,
  JumperPath,
  Layout,
  Schematic
} from '$lib/types';

function symbol(id: string, ref: string, pins: string[]): Schematic['nodes'][number] {
  return {
    kind: 'symbol',
    id,
    ref,
    value: null,
    footprintId: 'AXIAL-R',
    pins,
    x: 10,
    y: 10,
    rotation: 0
  };
}

function header(id: string, ref: string, pinCount: number): Schematic['nodes'][number] {
  const pins: string[] = [];
  for (let i = 1; i <= pinCount; i += 1) pins.push(String(i));
  return {
    kind: 'symbol',
    id,
    ref,
    value: null,
    footprintId: `HEADER-1x${pinCount}`,
    pins,
    x: 20,
    y: 10,
    rotation: 0
  };
}

function ic(id: string, ref: string, pinCount: number): Schematic['nodes'][number] {
  const pins: string[] = [];
  for (let i = 1; i <= pinCount; i += 1) pins.push(String(i));
  return {
    kind: 'symbol',
    id,
    ref,
    value: null,
    footprintId: `DIP-${pinCount}`,
    pins,
    x: 30,
    y: 10,
    rotation: 0
  };
}

function port(
  id: string,
  portKind: 'ground' | 'power' | 'label',
  netName: string
): Schematic['nodes'][number] {
  return {
    kind: 'port',
    id,
    portKind,
    netName,
    x: 0,
    y: 0,
    rotation: 0
  };
}

function conn(id: string, aNode: string, aPin: string | null, bNode: string, bPin: string | null): Schematic['connections'][number] {
  return {
    id,
    a: { nodeId: aNode, pin: aPin },
    b: { nodeId: bNode, pin: bPin }
  };
}

function placement(ref: string, anchor: string): ComponentPlacement {
  return {
    componentRef: ref,
    anchorHoleId: anchor,
    orientation: 0,
    span: null,
    pinHoles: {},
    occupiedHoleIds: [],
    locked: false
  };
}

function jumper(id: string, netId: string): Jumper {
  const path: JumperPath = { points: [], layer: 'lower' };
  return {
    id,
    netId,
    startHoleId: 'a1',
    endHoleId: 'a2',
    path,
    color: null,
    estimatedLengthMm: 0,
    locked: false
  };
}

function emptyLayout(overrides: Partial<Layout> = {}): Layout {
  return {
    version: 1,
    boardId: 'x',
    placements: [],
    jumpers: [],
    manualElectricalLinks: [],
    ...overrides
  };
}

describe('deriveNetlist', () => {
  it('joins two symbols via a single connection into one net', () => {
    const schematic: Schematic = {
      version: 1,
      nodes: [symbol('s-r1', 'R1', ['1', '2']), header('s-j1', 'J1', 2)],
      connections: [conn('w1', 's-r1', '1', 's-j1', '1')],
      netOverrides: []
    };

    const derived = deriveNetlist(schematic);
    // Natural sort: prefix J < prefix R, so J1 precedes R1.
    expect(derived.components.map((c) => c.ref)).toEqual(['J1', 'R1']);
    const r1 = derived.components.find((c) => c.ref === 'R1');
    expect(r1?.pins).toEqual(['1', '2']);
    expect(derived.nets).toHaveLength(1);
    // Pins sorted by natural ref comparator (J < R), so J1 first.
    expect(derived.nets[0].pins).toEqual([
      { componentRef: 'J1', pin: '1' },
      { componentRef: 'R1', pin: '1' }
    ]);
  });

  it('transitively merges three symbols across two connections', () => {
    const u1 = ic('s-u1', 'U1', 14);
    const schematic: Schematic = {
      version: 1,
      nodes: [
        symbol('s-r1', 'R1', ['1', '2']),
        symbol('s-c1', 'C1', ['1', '2']),
        u1
      ],
      connections: [
        conn('w1', 's-r1', '2', 's-c1', '1'),
        conn('w2', 's-c1', '1', 's-u1', '7')
      ],
      netOverrides: []
    };

    const derived = deriveNetlist(schematic);
    expect(derived.nets).toHaveLength(1);
    expect(derived.nets[0].pins).toEqual([
      { componentRef: 'C1', pin: '1' },
      { componentRef: 'R1', pin: '2' },
      { componentRef: 'U1', pin: '7' }
    ]);
  });

  it('uses ground port netName and collapses two separate GND ports into one net', () => {
    const withGround: Schematic = {
      version: 1,
      nodes: [
        symbol('s-r1', 'R1', ['1', '2']),
        port('p-gnd', 'ground', 'GND')
      ],
      connections: [conn('w1', 's-r1', '2', 'p-gnd', null)],
      netOverrides: []
    };
    const derived1 = deriveNetlist(withGround);
    expect(derived1.nets).toHaveLength(1);
    expect(derived1.nets[0].name).toBe('GND');
    expect(derived1.nets[0].netClass).toBe('ground');
    expect(derived1.nets[0].pins).toEqual([{ componentRef: 'R1', pin: '2' }]);

    const twoGrounds: Schematic = {
      version: 1,
      nodes: [
        symbol('s-r1', 'R1', ['1', '2']),
        symbol('s-c1', 'C1', ['1', '2']),
        port('p-gnd1', 'ground', 'GND'),
        port('p-gnd2', 'ground', 'GND')
      ],
      connections: [
        conn('w1', 's-r1', '1', 'p-gnd1', null),
        conn('w2', 's-c1', '1', 'p-gnd2', null)
      ],
      netOverrides: []
    };
    const derived2 = deriveNetlist(twoGrounds);
    expect(derived2.nets).toHaveLength(1);
    expect(derived2.nets[0].name).toBe('GND');
    expect(derived2.nets[0].pins).toEqual([
      { componentRef: 'C1', pin: '1' },
      { componentRef: 'R1', pin: '1' }
    ]);
  });

  it('produces deterministic N$1 / N$2 ordering independent of node array order', () => {
    const nodes: Schematic['nodes'] = [
      symbol('s-a', 'A', ['1', '2']),
      symbol('s-b', 'B', ['1', '2']),
      symbol('s-c', 'C', ['1', '2']),
      symbol('s-d', 'D', ['1', '2'])
    ];
    const connections = [
      conn('w1', 's-a', '1', 's-b', '1'),
      conn('w2', 's-c', '1', 's-d', '1')
    ];
    const original = deriveNetlist({ version: 1, nodes, connections, netOverrides: [] });
    const reversed = deriveNetlist({
      version: 1,
      nodes: [...nodes].reverse(),
      connections,
      netOverrides: []
    });
    expect(original.nets.map((n) => n.name)).toEqual(['N$1', 'N$2']);
    expect(reversed.nets.map((n) => n.name)).toEqual(['N$1', 'N$2']);
  });

  it('honors netOverrides netClass and priority over port-derived defaults', () => {
    const schematic: Schematic = {
      version: 1,
      nodes: [symbol('s-r1', 'R1', ['1', '2']), port('p-gnd', 'ground', 'GND')],
      connections: [conn('w1', 's-r1', '2', 'p-gnd', null)],
      netOverrides: [{ netName: 'GND', netClass: 'high-current', priority: 5 }]
    };
    const derived = deriveNetlist(schematic);
    expect(derived.nets).toHaveLength(1);
    expect(derived.nets[0].netClass).toBe('high-current');
    expect(derived.nets[0].priority).toBe(5);
  });

  it('ignores connections to unknown nodes and unknown pins without throwing', () => {
    const schematic: Schematic = {
      version: 1,
      nodes: [symbol('s-r1', 'R1', ['1', '2'])],
      connections: [
        conn('w-bad-node', 'missing', '1', 's-r1', '1'),
        conn('w-bad-pin', 's-r1', '99', 's-r1', '2')
      ],
      netOverrides: []
    };
    const derived = deriveNetlist(schematic);
    expect(derived.components).toHaveLength(1);
    // The bad-pin connection references the same node on both ends with
    // different pins, but the validation rejects the missing-pin endpoint,
    // so neither connection produces a union. Either way, no net should
    // ever contain the invalid pin '99'.
    for (const net of derived.nets) {
      for (const ref of net.pins) {
        expect(ref.pin).not.toBe('99');
        expect(ref.componentRef).toBe('R1');
      }
    }
  });
});

describe('pruneLayout', () => {
  it('drops placements and jumpers whose component/net vanished, keeps the rest', () => {
    const derived = deriveNetlist({
      version: 1,
      nodes: [symbol('s-r1', 'R1', ['1', '2'])],
      connections: [conn('w1', 's-r1', '1', 's-r1', '2')],
      netOverrides: []
    });
    const realNetId = derived.nets[0]?.id;
    expect(realNetId).toBeDefined();

    const layout: Layout = emptyLayout({
      placements: [placement('R1', 'a1'), placement('GONE', 'a2')],
      jumpers: [jumper('j1', realNetId as string), jumper('j2', 'net-gone')]
    });

    const pruned = pruneLayout(layout, derived);
    expect(pruned.placements.map((p) => p.componentRef)).toEqual(['R1']);
    expect(pruned.jumpers.map((j) => j.id)).toEqual(['j1']);
  });

  it('returns the same layout object reference when nothing was pruned', () => {
    const layout: Layout = emptyLayout({
      placements: [placement('R1', 'a1')],
      jumpers: [jumper('j1', 'net-r1-1')]
    });
    const derived = deriveNetlist({
      version: 1,
      nodes: [symbol('s-r1', 'R1', ['1', '2'])],
      connections: [conn('w1', 's-r1', '1', 's-r1', '2')],
      netOverrides: []
    });
    // Snap netId expectations to whatever the derivation produced.
    const expectedNetId = derived.nets[0]?.id;
    expect(expectedNetId).toBeDefined();
    layout.jumpers[0].netId = expectedNetId as string;

    const pruned = pruneLayout(layout, derived);
    expect(pruned).toBe(layout);
  });
});
