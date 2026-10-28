import { destinationFrom, type DestinationDraft } from '@/features/scheduledPosts/communities';
import type { ScheduledPost, ScheduledPostChanges } from '@/services/scheduledPostService';
import { dateTimeOf, instantOf, type DateTimeDraft } from '../postTo/WhenField';

/** The location state that opens a Post page on the inline edit, as Edit on a Posts row sends. */
export interface PostPageState {
  edit?: boolean;
}

export function opensEditing(state: unknown): boolean {
  return typeof state === 'object' && state !== null && (state as PostPageState).edit === true;
}

/** A Scheduled post's text, time and Destination as the inline edit holds them. */
export interface ScheduledPostEdit {
  texts: string[];
  when: DateTimeDraft;
  where: DestinationDraft;
}

/**
 * What saving `edit` changes on `scheduledPost`, holding only what differs; null while the
 * Destination or the time isn't readable yet. Checking the text is left to the API.
 */
export function changesFrom(
  scheduledPost: ScheduledPost,
  edit: ScheduledPostEdit,
): ScheduledPostChanges | null {
  const destination = destinationFrom(edit.where);
  const publishAt = instantOf(edit.when);
  if (!destination || !publishAt) return null;

  const changes: ScheduledPostChanges = {};
  const before = scheduledPost.parts.map((part) => part.text);
  if (edit.texts.length !== before.length || edit.texts.some((text, i) => text !== before[i])) {
    changes.parts = edit.texts;
  }
  const original = dateTimeOf(scheduledPost.publishAt);
  if (edit.when.date !== original.date || edit.when.time !== original.time) {
    changes.publishAt = publishAt;
  }
  const moves = destination.community?.id !== scheduledPost.community?.id;
  // Left out while the Community stays, so the Scheduled post keeps its stored name.
  if (moves) changes.community = destination.community;
  if (
    destination.community &&
    (moves || destination.shareWithFollowers !== scheduledPost.shareWithFollowers)
  ) {
    changes.shareWithFollowers = destination.shareWithFollowers;
  }
  return changes;
}
