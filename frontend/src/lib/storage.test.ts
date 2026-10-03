import { beforeEach, describe, expect, it } from 'vitest';
import { storage, storageKey } from './storage';

describe('storage', () => {
  beforeEach(() => localStorage.clear());

  it('namespaces keys with the app slug', () => {
    expect(storageKey('theme')).toBe('pumpkit:theme');
  });

  it('round-trips JSON values', () => {
    storage.set('sidebar-collapsed', true);
    expect(localStorage.getItem('pumpkit:sidebar-collapsed')).toBe('true');
    expect(storage.get('sidebar-collapsed', false)).toBe(true);
  });

  it('falls back on missing or corrupt values', () => {
    expect(storage.get('theme', 'system')).toBe('system');
    localStorage.setItem('pumpkit:theme', '{not json');
    expect(storage.get('theme', 'system')).toBe('system');
  });

  it('removes values', () => {
    storage.set('theme', 'dark');
    storage.remove('theme');
    expect(localStorage.getItem('pumpkit:theme')).toBeNull();
  });
});
