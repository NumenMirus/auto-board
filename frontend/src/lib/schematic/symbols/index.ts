import type { Component } from 'svelte';
import type { SymbolShape } from '../catalog';

import Resistor from './Resistor.svelte';
import Capacitor from './Capacitor.svelte';
import CapacitorPolar from './CapacitorPolar.svelte';
import Diode from './Diode.svelte';
import LED from './LED.svelte';
import Transistor from './Transistor.svelte';
import IC from './IC.svelte';
import Switch from './Switch.svelte';
import Header from './Header.svelte';
import Connector from './Connector.svelte';

/** Loose prop shape for the body fragment. Each symbol only reads the
 *  fields it needs; the others are passed as `undefined` and ignored. */
export type SymbolBodyProps = {
  strokeColor: string;
  halfCount?: number;
  pins?: number;
};

/**
 * Body fragment for each schematic symbol shape. Each component renders
 * only the body glyph (no halo, no label/value, no pin-name overlays) at
 * grid units in the parent's coordinate system. The parent supplies
 * `<g transform="translate scale">` and renders overlays.
 *
 * Replacing one shape = edit one file in this folder. Each file is a
 * drop-in replacement target for a decent hand-drawn SVG.
 */
export const SYMBOLS: Record<SymbolShape, Component<SymbolBodyProps>> = {
  resistor: Resistor as unknown as Component<SymbolBodyProps>,
  capacitor: Capacitor as unknown as Component<SymbolBodyProps>,
  'capacitor-polar': CapacitorPolar as unknown as Component<SymbolBodyProps>,
  diode: Diode as unknown as Component<SymbolBodyProps>,
  led: LED as unknown as Component<SymbolBodyProps>,
  transistor: Transistor as unknown as Component<SymbolBodyProps>,
  ic: IC as unknown as Component<SymbolBodyProps>,
  switch: Switch as unknown as Component<SymbolBodyProps>,
  header: Header as unknown as Component<SymbolBodyProps>,
  connector: Connector as unknown as Component<SymbolBodyProps>
};
