import { useMemo, useState, type FormEvent } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import { xWeightedLength } from '@/lib/xLength';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { localInputValue } from './localTime';
import { PublishTimeField } from './PublishTimeField';
import { XLengthCounter } from './XLengthCounter';

export type ScheduledPostChanges = { text?: string; publishAt?: string };

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
  const [text, setText] = useState(post.text);
  const [when, setWhen] = useState(originalWhen);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const length = useMemo(() => xWeightedLength(text), [text]);

  const changes: ScheduledPostChanges = {};
  if (text !== post.text) changes.text = text;
  // A datetime-local value without an offset parses as local time.
  if (when && when !== originalWhen) changes.publishAt = new Date(when).toISOString();
  const nothingToSave = failed ? !changes.publishAt : !changes.text && !changes.publishAt;

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
            : 'Change the text or the time before it goes out.'}
        </DialogDescription>
      </DialogHeader>
      <div className="space-y-3 px-6 pb-4">
        <label htmlFor="edit-scheduled-post-text" className="sr-only">
          Post text
        </label>
        <Textarea
          id="edit-scheduled-post-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          disabled={saving}
        />
        <XLengthCounter length={length} limit={charLimit} />
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
          disabled={saving || nothingToSave || length > charLimit || !text.trim()}
        >
          {failed ? 'Reschedule' : 'Save'}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Changes the text or time of a scheduled Scheduled post, or reschedules a Failed one. */
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
