/**
 * Phase 4c — client-side preview math mirrors the server's
 * splits.py algorithm. These tests are tight on a few edge cases
 * the server's Hypothesis suite already covers more broadly.
 */
import { describe, expect, it } from 'vitest';

import {
  previewEqualSplit,
  previewPercentSplit,
  previewShareSplit,
  sumAmounts,
} from '~/lib/splits';

describe('previewEqualSplit', () => {
  it('clean two-way split', () => {
    expect(previewEqualSplit('10.00', 2)).toEqual(['5.00', '5.00']);
  });

  it('three-way split puts remainder on the last member', () => {
    expect(previewEqualSplit('10.00', 3)).toEqual(['3.33', '3.33', '3.34']);
  });

  it('tiny amount across many members keeps the absorber non-negative', () => {
    // 0.02 / 4 = floor(0.005) = 0.00 each for first 3, last absorbs 0.02.
    const out = previewEqualSplit('0.02', 4);
    expect(out).toEqual(['0.00', '0.00', '0.00', '0.02']);
    expect(sumAmounts(out)).toBe('0.02');
  });
});

describe('previewShareSplit', () => {
  it('1:2:1 across $100 → 25 / 50 / 25', () => {
    expect(previewShareSplit('100.00', ['1', '2', '1'])).toEqual(['25.00', '50.00', '25.00']);
  });
});

describe('previewPercentSplit', () => {
  it('25 / 25 / 50 across $200 → 50 / 50 / 100', () => {
    expect(previewPercentSplit('200.00', ['25', '25', '50'])).toEqual(['50.00', '50.00', '100.00']);
  });
});

describe('sumAmounts', () => {
  it('sums non-negative monetary strings exactly', () => {
    expect(sumAmounts(['10.00', '3.50', '0.50'])).toBe('14.00');
  });

  it('returns 0.00 for an empty list', () => {
    expect(sumAmounts([])).toBe('0.00');
  });
});
