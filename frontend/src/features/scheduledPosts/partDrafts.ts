import { xWeightedLength } from '@/lib/xLength';
import type { ScheduledPostPart } from '@/services/scheduledPostService';

/**
 * One Part as the editor holds it; `key` keeps a text area attached to its Part as Parts move.
 * A `live` one is on X, so it stays first and unchanged (ADR 0014).
 */
export interface PartDraft {
  key: number;
  text: string;
  live: boolean;
  xPostUrl: string | null;
}

let nextKey = 0;

export function partDrafts(texts: string[]): PartDraft[] {
  return texts.map((text) => ({ key: nextKey++, text, live: false, xPostUrl: null }));
}

/** The Parts of a Scheduled post, live ones included. */
export function scheduledPartDrafts(parts: ScheduledPostPart[]): PartDraft[] {
  return parts.map((part) => ({
    key: nextKey++,
    text: part.text,
    live: part.live,
    xPostUrl: part.xPostUrl,
  }));
}

export function partTexts(drafts: PartDraft[]): string[] {
  return drafts.map((draft) => draft.text);
}

/**
 * Whether there is a Part not live, and every one has text and fits `charLimit` by X's count.
 * With only live Parts left, a reschedule would publish nothing.
 */
export function partsSendable(drafts: PartDraft[], charLimit: number): boolean {
  return (
    drafts.some((draft) => !draft.live) &&
    drafts.every(
      (draft) => draft.live || (draft.text.trim() && xWeightedLength(draft.text) <= charLimit),
    )
  );
}
