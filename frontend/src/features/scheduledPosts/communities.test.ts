import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { communityIdFrom } from './communities';

// The backend's cases, so the Where field reads a paste the way the server's lookup will.
const CASES: { note: string; pasted: string; id: string | null }[] = JSON.parse(
  readFileSync(
    path.resolve(__dirname, '../../../../backend/tests/scheduling/community_paste_cases.json'),
    'utf8',
  ),
);

describe('communityIdFrom', () => {
  it.each(CASES)('$note', ({ pasted, id }) => {
    expect(communityIdFrom(pasted)).toBe(id);
  });
});
