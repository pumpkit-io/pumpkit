import { storage } from '@/lib/storage';
import type { PostDetail, PostListItem } from '@/services/postService';

/** How many Drafts the Drafts tab keeps under Recently opened. */
export const RECENT_DRAFTS_MAX = 3;
/** How long a Draft stays under Recently opened without being opened again. */
export const RECENT_DRAFT_TTL_MS = 48 * 60 * 60 * 1000;

interface Opened {
  id: string;
  /** Epoch milliseconds. */
  at: number;
}

function read(now: number): Opened[] {
  let value: unknown;
  try {
    value = storage.get<unknown>('recent-drafts', []);
  } catch {
    // Blocked storage leaves the list empty rather than breaking the Drafts tab.
    return [];
  }
  if (!Array.isArray(value)) return [];
  return value
    .filter((o): o is Opened => {
      if (typeof o?.id !== 'string' || typeof o?.at !== 'number') return false;
      // A negative age means the clock was ahead when it was recorded.
      const age = now - o.at;
      return age >= 0 && age < RECENT_DRAFT_TTL_MS;
    })
    .slice(0, RECENT_DRAFTS_MAX);
}

/** Puts the Draft at the top of Recently opened, dropping the oldest past the limit. */
export function recordDraftOpened(id: string, now = Date.now()): void {
  const kept = read(now).filter((o) => o.id !== id);
  try {
    storage.set('recent-drafts', [{ id, at: now }, ...kept].slice(0, RECENT_DRAFTS_MAX));
  } catch {
    // Full or blocked storage must not stop the Post page from opening.
  }
}

/** The Posts under Recently opened, most recently opened first; some may no longer be Drafts. */
export function recentDraftIds(now = Date.now()): string[] {
  return read(now).map((o) => o.id);
}

/** A Draft as the Drafts tab lists it, built as the server builds a Draft's row. */
export function draftListItem(post: PostDetail): PostListItem | null {
  const latest = post.versions[post.versions.length - 1];
  if (!latest) return null;
  return {
    id: post.id,
    brief: post.brief,
    status: post.status,
    parts: latest.parts.map((p) => p.text),
    format: latest.format,
    versionCount: post.versions.length,
    latestVersionAt: latest.createdAt,
    scheduledPost: null,
  };
}
