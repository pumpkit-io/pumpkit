import { xWeightedLength } from '@/lib/xLength';

/** One Part as the editor holds it; `key` keeps a text area attached to its Part as Parts move. */
export interface PartDraft {
  key: number;
  text: string;
}

let nextKey = 0;

export function partDrafts(texts: string[]): PartDraft[] {
  return texts.map((text) => ({ key: nextKey++, text }));
}

export function partTexts(drafts: PartDraft[]): string[] {
  return drafts.map((draft) => draft.text);
}

/** Whether every Part has text and fits `charLimit` by X's count. */
export function partsSendable(drafts: PartDraft[], charLimit: number): boolean {
  return drafts.every((draft) => draft.text.trim() && xWeightedLength(draft.text) <= charLimit);
}
