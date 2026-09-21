import type { SchematicPortKind } from '$lib/types';

export type SymbolShape =
  | 'resistor'
  | 'capacitor'
  | 'capacitor-polar'
  | 'diode'
  | 'led'
  | 'transistor'
  | 'ic'
  | 'switch'
  | 'header'
  | 'connector';

export type PaletteGroup =
  | 'Passives'
  | 'Semiconductors'
  | 'ICs'
  | 'Switches'
  | 'Connectors'
  | 'Power';

export interface PaletteEntry {
  footprintId: string;
  label: string;
  shape: SymbolShape;
  refPrefix: string;
  defaultValue: string | null;
  group: PaletteGroup;
}

export interface PortPaletteEntry {
  portKind: SchematicPortKind;
  label: string;
  defaultNetName: string;
}

const DIP_PIN_COUNTS = [8, 14, 16, 20, 28] as const;
const HEADER_PIN_COUNTS: number[] = [];
for (let n = 2; n <= 10; n += 1) HEADER_PIN_COUNTS.push(n);
const CONNECTOR_PIN_COUNTS: number[] = [];
for (let n = 2; n <= 4; n += 1) CONNECTOR_PIN_COUNTS.push(n);

export const PALETTE: PaletteEntry[] = [
  { footprintId: 'AXIAL-R', label: 'Resistor', shape: 'resistor', refPrefix: 'R', defaultValue: '10k', group: 'Passives' },
  { footprintId: 'RADIAL-CAP-2P', label: 'Capacitor', shape: 'capacitor', refPrefix: 'C', defaultValue: '100n', group: 'Passives' },
  { footprintId: 'ELECTROLYTIC-CAP-2P', label: 'Electrolytic cap', shape: 'capacitor-polar', refPrefix: 'C', defaultValue: '10u', group: 'Passives' },
  { footprintId: 'AXIAL-DIODE', label: 'Diode', shape: 'diode', refPrefix: 'D', defaultValue: '1N4148', group: 'Semiconductors' },
  { footprintId: 'LED-2P', label: 'LED', shape: 'led', refPrefix: 'D', defaultValue: null, group: 'Semiconductors' },
  { footprintId: 'TO-92', label: 'Transistor (TO-92)', shape: 'transistor', refPrefix: 'Q', defaultValue: 'BC547', group: 'Semiconductors' },
  ...DIP_PIN_COUNTS.map((n) => ({
    footprintId: `DIP-${n}`,
    label: `DIP-${n}`,
    shape: 'ic' as const,
    refPrefix: 'U',
    defaultValue: null,
    group: 'ICs' as const
  })),
  { footprintId: 'TACT-SW-4P', label: 'Tact switch', shape: 'switch', refPrefix: 'SW', defaultValue: null, group: 'Switches' },
  ...HEADER_PIN_COUNTS.map((n) => ({
    footprintId: `HEADER-1x${n}`,
    label: `Header 1\u00d7${n}`,
    shape: 'header' as const,
    refPrefix: 'J',
    defaultValue: null,
    group: 'Connectors' as const
  })),
  ...CONNECTOR_PIN_COUNTS.map((n) => ({
    footprintId: `CONN-1x${n}`,
    label: `Connector 1\u00d7${n}`,
    shape: 'connector' as const,
    refPrefix: 'J',
    defaultValue: null,
    group: 'Connectors' as const
  }))
];

export const PORT_PALETTE: PortPaletteEntry[] = [
  { portKind: 'ground', label: 'Ground', defaultNetName: 'GND' },
  { portKind: 'power', label: 'Power', defaultNetName: 'VCC' },
  { portKind: 'label', label: 'Net label', defaultNetName: 'NET' }
];

/** Falls back to 'ic' for a footprint the palette does not list. */
export function shapeFor(footprintId: string): SymbolShape {
  return PALETTE.find((p) => p.footprintId === footprintId)?.shape ?? 'ic';
}

export function paletteEntryFor(footprintId: string): PaletteEntry | undefined {
  return PALETTE.find((p) => p.footprintId === footprintId);
}

/** Lowest positive integer not present in `taken`, e.g. ('R', ['R1','R3']) -> 'R2'. */
export function nextRef(prefix: string, taken: readonly string[]): string {
  const used = new Set(taken);
  let n = 1;
  while (used.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

/** Lowest positive integer id not present, e.g. ('sym', [...]) -> 'sym-4'. */
export function nextNodeId(
  prefix: 'sym' | 'port' | 'w',
  taken: readonly string[]
): string {
  const used = new Set(taken);
  let n = 1;
  while (used.has(`${prefix}-${n}`)) n += 1;
  return `${prefix}-${n}`;
}
