import { describe, expect, it } from 'vitest';
import { APP_NAME, APP_SLUG, toSlug } from './app';

describe('app identity', () => {
  it('defaults the app name', () => {
    expect(APP_NAME).toBe('Pumpkit');
    expect(APP_SLUG).toBe('pumpkit');
  });

  it('slugifies names', () => {
    expect(toSlug('My Cool App!')).toBe('my-cool-app');
    expect(toSlug('  ')).toBe('app');
  });
});
