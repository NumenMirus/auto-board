import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/svelte';
import MetricsBar from './MetricsBar.svelte';
import type { LayoutScore } from '$lib/types';

describe('MetricsBar', () => {
  it('renders the empty state when no score is provided', () => {
    const { container } = render(MetricsBar, { props: { score: null } });
    const text = container.textContent ?? '';
    expect(text).toContain('no score yet');
    // None of the metric rows should appear when there's no score.
    expect(text).not.toContain('Placed');
    expect(text).not.toContain('Nets complete');
  });

  it('renders every metric line when given a score', () => {
    const score: LayoutScore = {
      total: 1234.6,
      placementCost: 100,
      routingCost: 200,
      componentsPlaced: 8,
      componentsTotal: 10,
      netsCompleted: 5,
      netsTotal: 7,
      jumperCount: 12,
      totalJumperLengthMm: 3450,
      crossings: 2,
      errorCount: 1,
      warningCount: 3
    };
    const { container } = render(MetricsBar, { props: { score } });
    const text = container.textContent ?? '';
    expect(text).toContain('Placed');
    expect(text).toContain('8 / 10');
    expect(text).toContain('Nets complete');
    expect(text).toContain('5 / 7');
    expect(text).toContain('Wires');
    expect(text).toContain('12');
    // 3450 mm -> 3.45 m (mm/1000, 2 decimals).
    expect(text).toContain('3.45');
    expect(text).toContain('Crossings');
    expect(text).toContain('2');
    expect(text).toContain('Errors');
    expect(text).toContain('1');
    expect(text).toContain('Warnings');
    expect(text).toContain('3');
    expect(text).toContain('Score');
    // Math.round(1234.6) -> 1235
    expect(text).toContain('1235');
  });
});