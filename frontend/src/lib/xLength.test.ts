import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { xWeightedLength } from './xLength';
import { X_TLDS } from './xTlds';

const backendPublishing = path.resolve(__dirname, '../../../backend/app/publishing');

// The backend's cases, so the composer's counter and the backend's check agree.
const CASES: { note: string; text: string; length: number }[] = JSON.parse(
  readFileSync(
    path.resolve(__dirname, '../../../backend/app/tests/publishing/x_weighted_length_cases.json'),
    'utf8',
  ),
);

describe('xWeightedLength', () => {
  it.each(CASES)('$note', ({ text, length }) => {
    expect(xWeightedLength(text)).toBe(length);
  });

  it('counts a long run of dotted labels without stalling', () => {
    expect(xWeightedLength('a.'.repeat(12_500))).toBe(25_000);
  });

  it('knows the same TLDs as the backend', () => {
    const backend = readFileSync(path.join(backendPublishing, 'x_tlds.txt'), 'utf8')
      .split('\n')
      .filter((line) => line && !line.startsWith('#'));
    expect(X_TLDS).toEqual(backend);
  });
});
