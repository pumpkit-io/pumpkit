import Fuse, { type IFuseOptions } from 'fuse.js';
import type { AuthorDirectoryEntry } from '@/services/authorDirectoryService';

/** One row of the author picker: a directory entry, or a lookup of the query's handle on X. */
export type AuthorRow =
  { kind: 'directory'; entry: AuthorDirectoryEntry } | { kind: 'lookup'; handle: string };

// Tuned on the seeds: "levlsio" scores 0.31 against levelsio and stays; "foobar" (0.38 against
// byrnehobart) and "blorft" (0.52 against taylorotwell) drop. At 0.4, "naavl" and "lorem" match strangers.
export const MIN_MATCH_SCORE = 0.35;

const FUSE_OPTIONS: IFuseOptions<AuthorDirectoryEntry> = {
  keys: [
    { name: 'handle', weight: 0.6 },
    { name: 'name', weight: 0.4 },
  ],
  includeScore: true,
  threshold: MIN_MATCH_SCORE,
  ignoreLocation: true,
  ignoreDiacritics: true,
};

const HANDLE_SHAPED = /^@?[A-Za-z0-9_]{1,15}$/;

function fold(text: string): string {
  return text
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase();
}

function byPicksThenName(a: AuthorDirectoryEntry, b: AuthorDirectoryEntry): number {
  return b.personaCount - a.personaCount || (a.name ?? a.handle).localeCompare(b.name ?? b.handle);
}

/** 0 for the exact handle, 1 for a handle or name-word prefix, 2 for any other fuzzy match. */
function tier(entry: AuthorDirectoryEntry, term: string): number {
  if (entry.handle === term) return 0;
  const words = fold(entry.name ?? '').split(/\s+/);
  if (entry.handle.startsWith(term) || words.some((word) => word.startsWith(term))) return 1;
  return 2;
}

/**
 * A search over the whole Author directory, kept in the browser (ADR 0019). Entries in `hidden`
 * (the User's Persona) never show.
 */
export function createAuthorSearch(directory: AuthorDirectoryEntry[], hidden: Set<string>) {
  const shown = directory.filter((entry) => !hidden.has(entry.handle));
  const known = new Set(directory.map((entry) => entry.handle));
  const fuse = new Fuse(shown, FUSE_OPTIONS);

  return (query: string): AuthorRow[] => {
    const typed = query.trim();
    if (!typed) {
      return [...shown].sort(byPicksThenName).map((entry) => ({ kind: 'directory', entry }));
    }
    const term = fold(typed.replace(/^@/, ''));
    const matches: AuthorRow[] = fuse
      .search(term)
      .filter((result) => (result.score ?? 1) <= MIN_MATCH_SCORE)
      .map((result, index) => ({ result, index, tier: tier(result.item, term) }))
      .sort(
        (a, b) =>
          a.tier - b.tier ||
          (a.result.score ?? 1) - (b.result.score ?? 1) ||
          byPicksThenName(a.result.item, b.result.item) ||
          a.index - b.index,
      )
      .map(({ result }) => ({ kind: 'directory', entry: result.item }));

    if (!HANDLE_SHAPED.test(typed) || known.has(term)) return matches;
    // "@" means exactly that handle; without it, a name never spends a lookup on a stranger.
    const lookup: AuthorRow = { kind: 'lookup', handle: term };
    return typed.startsWith('@') ? [lookup, ...matches] : [...matches, lookup];
  };
}
