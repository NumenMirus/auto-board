import type {
  Component,
  Layout,
  Net,
  NetClass,
  PinRef,
  Schematic,
  SchematicNode,
  SchematicPortNode,
  SchematicSymbolNode
} from '$lib/types';

export interface DerivedNetlist {
  components: Component[];
  nets: Net[];
}

export const AUTO_NET_PREFIX = 'N$';

interface EndpointEntry {
  /** ``${nodeId}\u0000${pin ?? '*'}`` */
  key: string;
  nodeId: string;
  pin: string;
  /** Whether this endpoint refers to a port node (terminal = '*'). */
  isPort: boolean;
}

class DisjointSetUnion {
  private readonly parent = new Map<string, string>();
  private readonly rank = new Map<string, number>();

  make(key: string): void {
    if (!this.parent.has(key)) {
      this.parent.set(key, key);
      this.rank.set(key, 0);
    }
  }

  find(key: string): string {
    let root = key;
    while (this.parent.get(root) !== root) {
      root = this.parent.get(root) as string;
    }
    // Path compression.
    let cur = key;
    while (this.parent.get(cur) !== root) {
      const next = this.parent.get(cur) as string;
      this.parent.set(cur, root);
      cur = next;
    }
    return root;
  }

  union(a: string, b: string): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra === rb) return;
    const rankA = this.rank.get(ra) ?? 0;
    const rankB = this.rank.get(rb) ?? 0;
    if (rankA < rankB) {
      this.parent.set(ra, rb);
    } else if (rankA > rankB) {
      this.parent.set(rb, ra);
    } else {
      this.parent.set(rb, ra);
      this.rank.set(ra, rankA + 1);
    }
  }
}

function endpointKey(nodeId: string, pin: string | null): string {
  return `${nodeId}\u0000${pin ?? '*'}`;
}

function parseRef(ref: string): { prefix: string; num: number | null; suffix: string } {
  const match = /^([A-Za-z]+)(\d+)(.*)$/.exec(ref);
  if (match) {
    return { prefix: match[1], num: Number(match[2]), suffix: match[3] };
  }
  return { prefix: ref, num: null, suffix: '' };
}

export function compareRef(a: string, b: string): number {
  const pa = parseRef(a);
  const pb = parseRef(b);
  if (pa.prefix !== pb.prefix) {
    return pa.prefix < pb.prefix ? -1 : 1;
  }
  if (pa.num !== null && pb.num !== null) {
    if (pa.num !== pb.num) return pa.num - pb.num;
    if (pa.suffix !== pb.suffix) return pa.suffix < pb.suffix ? -1 : 1;
    return 0;
  }
  if (pa.num !== null) return -1;
  if (pb.num !== null) return 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

function comparePin(a: string, b: string): number {
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb) && Number.isFinite(na) && Number.isFinite(nb)) {
    return na - nb;
  }
  return a < b ? -1 : a > b ? 1 : 0;
}

function comparePinRef(a: PinRef, b: PinRef): number {
  const byRef = compareRef(a.componentRef, b.componentRef);
  if (byRef !== 0) return byRef;
  return comparePin(a.pin, b.pin);
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/**
 * Derives the project `components` and `nets` from the schematic drawing.
 * Pure: same input always produces the same output, in a deterministic order.
 */
export function deriveNetlist(schematic: Schematic): DerivedNetlist {
  const nodesById = new Map<string, SchematicNode>();
  for (const node of schematic.nodes) {
    nodesById.set(node.id, node);
  }

  // Components: one per symbol node, sorted by ref.
  const symbolNodes: SchematicSymbolNode[] = [];
  for (const node of schematic.nodes) {
    if (node.kind === 'symbol') symbolNodes.push(node);
  }
  symbolNodes.sort((a, b) => compareRef(a.ref, b.ref));

  const components: Component[] = symbolNodes.map((node) => ({
    ref: node.ref,
    value: node.value,
    footprintId: node.footprintId,
    pins: [...node.pins],
    locked: false,
    tags: []
  }));

  const refByNodeId = new Map<string, string>();
  for (const node of symbolNodes) refByNodeId.set(node.id, node.ref);

  // Walk connections to build the union-find.
  const dsu = new DisjointSetUnion();
  // Track every endpoint key we union so we can later map root -> entries.
  const entries: EndpointEntry[] = [];

  for (const conn of schematic.connections) {
    const aNode = nodesById.get(conn.a.nodeId);
    const bNode = nodesById.get(conn.b.nodeId);
    if (!aNode || !bNode) continue;

    const aPin = conn.a.pin;
    const bPin = conn.b.pin;

    if (aNode.kind === 'symbol') {
      if (aPin === null) continue;
      if (!aNode.pins.includes(aPin)) continue;
    }
    if (bNode.kind === 'symbol') {
      if (bPin === null) continue;
      if (!bNode.pins.includes(bPin)) continue;
    }

    const aKey = endpointKey(conn.a.nodeId, aPin);
    const bKey = endpointKey(conn.b.nodeId, bPin);

    dsu.make(aKey);
    dsu.make(bKey);

    // Record the endpoints for later grouping.
    pushEntry(entries, {
      key: aKey,
      nodeId: conn.a.nodeId,
      pin: aPin ?? '*',
      isPort: aNode.kind === 'port'
    });
    pushEntry(entries, {
      key: bKey,
      nodeId: conn.b.nodeId,
      pin: bPin ?? '*',
      isPort: bNode.kind === 'port'
    });

    dsu.union(aKey, bKey);
  }

  // Group entries by DSU root.
  const groups = new Map<string, EndpointEntry[]>();
  for (const entry of entries) {
    const root = dsu.find(entry.key);
    let bucket = groups.get(root);
    if (!bucket) {
      bucket = [];
      groups.set(root, bucket);
    }
    bucket.push(entry);
  }

  // Resolve name per group.
  interface ResolvedGroup {
    root: string;
    resolvedName: string | null; // null = auto-named
    entries: EndpointEntry[];
  }
  const resolved: ResolvedGroup[] = [];
  for (const [root, bucket] of groups) {
    const portNames: string[] = [];
    for (const e of bucket) {
      if (!e.isPort) continue;
      const node = nodesById.get(e.nodeId) as SchematicPortNode | undefined;
      if (node) portNames.push(node.netName);
    }
    if (portNames.length > 0) {
      portNames.sort();
      resolved.push({ root, resolvedName: portNames[0], entries: bucket });
    } else {
      resolved.push({ root, resolvedName: null, entries: bucket });
    }
  }

  // Merge groups sharing the same non-auto resolved name.
  const namedGroups = new Map<string, EndpointEntry[]>();
  const unnamedGroups: EndpointEntry[] = [];
  for (const g of resolved) {
    if (g.resolvedName !== null) {
      const existing = namedGroups.get(g.resolvedName);
      if (existing) {
        existing.push(...g.entries);
      } else {
        namedGroups.set(g.resolvedName, [...g.entries]);
      }
    } else {
      unnamedGroups.push(...g.entries);
    }
  }

  // Build nets from merged groups.
  const nets: Net[] = [];

  for (const [name, bucket] of namedGroups) {
    const merged = buildNet(name, bucket, nodesById, refByNodeId, schematic);
    if (merged) nets.push(merged);
  }


  // Recompute unnamed groups grouped by root, in deterministic key order.
  const rootsForUnnamed = new Map<string, EndpointEntry[]>();
  for (const entry of unnamedGroups) {
    // entry.key is itself the key; DSU root is what we want for grouping.
    // We can recover the root by using dsu.find on each unique key.
    const root = dsu.find(entry.key);
    let bucket = rootsForUnnamed.get(root);
    if (!bucket) {
      bucket = [];
      rootsForUnnamed.set(root, bucket);
    }
    bucket.push(entry);
  }

  const sortedUnnamedRoots = Array.from(rootsForUnnamed.keys()).sort();
  let autoIndex = 1;
  for (const _root of sortedUnnamedRoots) {
    const bucket = rootsForUnnamed.get(_root) as EndpointEntry[];
    const name = `${AUTO_NET_PREFIX}${autoIndex}`;
    autoIndex += 1;
    const merged = buildNet(name, bucket, nodesById, refByNodeId, schematic);
    if (merged) nets.push(merged);
  }

  nets.sort((a, b) => compareRef(a.name, b.name));

  return { components, nets };
}

function pushEntry(list: EndpointEntry[], entry: EndpointEntry): void {
  // Avoid duplicate entries for the same key (parallel connections between
  // the same two endpoints should still result in one net).
  for (const existing of list) {
    if (existing.key === entry.key) return;
  }
  list.push(entry);
}

function buildNet(
  name: string,
  bucket: EndpointEntry[],
  nodesById: Map<string, SchematicNode>,
  refByNodeId: Map<string, string>,
  schematic: Schematic
): Net | null {
  const pins: PinRef[] = [];
  let hasGround = false;
  let hasPower = false;

  for (const entry of bucket) {
    if (entry.isPort) {
      const node = nodesById.get(entry.nodeId) as SchematicPortNode | undefined;
      if (node) {
        if (node.portKind === 'ground') hasGround = true;
        else if (node.portKind === 'power') hasPower = true;
      }
      continue;
    }
    const ref = refByNodeId.get(entry.nodeId);
    if (!ref) continue;
    pins.push({ componentRef: ref, pin: entry.pin });
  }

  if (pins.length === 0) return null;

  pins.sort(comparePinRef);

  let netClass: NetClass;
  let priority = 0;

  const override = schematic.netOverrides.find((o) => o.netName === name);
  if (override) {
    netClass = override.netClass;
    priority = override.priority;
  } else if (hasGround) {
    netClass = 'ground';
  } else if (hasPower) {
    netClass = 'power';
  } else {
    netClass = 'digital';
  }

  return {
    id: `net-${slugify(name)}`,
    name,
    pins,
    netClass,
    priority,
    constraints: []
  };
}

/**
 * Removes layout entries that no longer have a corresponding component or
 * net after derivation. Returns the exact same object reference when no
 * pruning is necessary.
 */
export function pruneLayout(layout: Layout, derived: DerivedNetlist): Layout {
  const refs = new Set(derived.components.map((c) => c.ref));
  const netIds = new Set(derived.nets.map((n) => n.id));

  const placements = layout.placements.filter((p) => refs.has(p.componentRef));
  const jumpers = layout.jumpers.filter((j) => netIds.has(j.netId));
  const manualElectricalLinks = layout.manualElectricalLinks.filter(
    (l) => l.netId === null || netIds.has(l.netId)
  );

  if (
    placements.length === layout.placements.length &&
    jumpers.length === layout.jumpers.length &&
    manualElectricalLinks.length === layout.manualElectricalLinks.length
  ) {
    return layout;
  }

  return { ...layout, placements, jumpers, manualElectricalLinks };
}
