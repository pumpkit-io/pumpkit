import { useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { ScheduledPost, ScheduledPostChanges } from '@/services/scheduledPostService';
import { destinationFrom, PROFILE_DRAFT, type DestinationDraft } from './communities';
import { DestinationField } from './DestinationField';
import { localInputValue } from './localTime';
import { PartEditor } from './PartEditor';
import { partsSendable, partTexts, scheduledPartDrafts } from './partDrafts';
import { PublishTimeField } from './PublishTimeField';

function draftOf(post: ScheduledPost): DestinationDraft {
  if (!post.community) return PROFILE_DRAFT;
  return {
    kind: 'pastCommunity',
    community: { id: post.community.id, name: post.community.name },
    shareWithFollowers: post.shareWithFollowers,
  };
}

function EditForm({
  post,
  charLimit,
  onClose,
  onSave,
}: {
  post: ScheduledPost;
  charLimit: number;
  onClose: () => void;
  onSave: (changes: ScheduledPostChanges) => Promise<string | null>;
}) {
  const failed = post.state === 'failed';
  // A Failed one's time has passed: it needs a new one.
  const originalWhen = failed ? '' : localInputValue(new Date(post.publishAt));
  const originalTexts = post.parts.map((part) => part.text);
  const [parts, setParts] = useState(() => scheduledPartDrafts(post.parts));
  const [when, setWhen] = useState(originalWhen);
  const [draft, setDraft] = useState(() => draftOf(post));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changes: ScheduledPostChanges = {};
  const texts = partTexts(parts);
  if (texts.length !== originalTexts.length || texts.some((t, i) => t !== originalTexts[i])) {
    changes.parts = texts;
  }
  // A datetime-local value without an offset parses as local time.
  if (when && when !== originalWhen) changes.publishAt = new Date(when).toISOString();
  const destination = destinationFrom(draft);
  if (destination) {
    const movesCommunity = destination.community?.id !== post.community?.id;
    // Left out while the Community stays, so the edit keeps its stored name.
    if (movesCommunity) changes.community = destination.community;
    const share = destination.shareWithFollowers;
    if (destination.community && (movesCommunity || share !== post.shareWithFollowers)) {
      changes.shareWithFollowers = share;
    }
  }
  const nothingToSave = failed ? !changes.publishAt : Object.keys(changes).length === 0;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const refused = await onSave(changes);
    setSaving(false);
    if (refused) setError(refused);
    else onClose();
  };

  return (
    <form onSubmit={save}>
      <DialogHeader>
        <DialogTitle className="font-sans text-base font-semibold tracking-tight">
          {failed ? 'Reschedule' : 'Edit Scheduled post'}
        </DialogTitle>
        <DialogDescription className="font-sans">
          {failed
            ? 'Pick a new time. It goes out on the X account connected now.'
            : 'Change the text, the time or the Community before it goes out.'}
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-3 px-6 pb-4">
        <PartEditor parts={parts} onChange={setParts} charLimit={charLimit} disabled={saving} />
        <DestinationField value={draft} onChange={setDraft} disabled={saving} />
        <PublishTimeField value={when} onChange={setWhen} disabled={saving} />
        {error && <ErrorBanner message={error} />}
      </div>
      <DialogFooter className="justify-end gap-2">
        <Button type="button" variant="outline" className="h-10" onClick={onClose}>
          Back
        </Button>
        <Button
          type="submit"
          className="h-10"
          disabled={saving || nothingToSave || !destination || !partsSendable(parts, charLimit)}
        >
          {failed ? 'Reschedule' : 'Save'}
        </Button>
      </DialogFooter>
    </form>
  );
}

/**
 * Changes the text, time or Community of a scheduled Scheduled post, or reschedules a Failed
 * one, with the same changes.
 */
export function EditScheduledPostDialog({
  post,
  charLimit,
  onClose,
  onSave,
}: {
  /** Null when closed. */
  post: ScheduledPost | null;
  charLimit: number;
  onClose: () => void;
  onSave: (changes: ScheduledPostChanges) => Promise<string | null>;
}) {
  return (
    <Dialog open={post !== null} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-[560px] max-sm:h-auto">
        {post && (
          <EditForm
            key={post.id}
            post={post}
            charLimit={charLimit}
            onClose={onClose}
            onSave={onSave}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
