import { describe, expect, it } from 'vitest';
import { formatAmount } from './money';

describe('formatAmount', () => {
  it('formats minor units with the currency', () => {
    expect(formatAmount(1000, 'eur', 'en-US')).toBe('€10.00');
    expect(formatAmount(1999, 'usd', 'en-US')).toBe('$19.99');
  });
});
