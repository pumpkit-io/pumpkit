import { afterEach, describe, expect, it } from 'vitest';
import { APP_SLUG, setAppSlug, toSlug } from './app';
import { storageKey } from './storage';

describe('app identity', () => {
  afterEach(() => setAppSlug('Pumpkit'));

  it('defaults the slug until the Instance loads', () => {
    expect(APP_SLUG).toBe('pumpkit');
  });

  it("namespaces storage keys with the Instance's app name once loaded", () => {
    setAppSlug('Acme Writer');
    expect(storageKey('theme')).toBe('acme-writer:theme');
  });

  it('slugifies names', () => {
    expect(toSlug('My Cool App!')).toBe('my-cool-app');
    expect(toSlug('  ')).toBe('app');
  });
});
