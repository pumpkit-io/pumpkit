import { useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import { xWeightedLength } from '@/lib/xLength';
import type { Version } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { Panel } from '../panels/panelParts';
import { DateTimeFields, dateTimeOf } from '../postTo/WhenField';
import { WhereField } from '../postTo/WhereField';
import type { ShownPart } from '../shownText';
import { VersionCard } from '../VersionCard';
import { changesFrom, type ScheduledPostEdit } from './scheduledPostEdit';
import { useScheduledPostActions } from './useScheduledPostActions';

/** A waiting Scheduled post edited in place; only its copy changes, never the Version's text. */
export function ScheduledPostEditor({
  version,
  scheduledPost,
  charLimit,
  onSaved,
  onUnscheduled,
  onCancel,
}: {
  /** The Version the Scheduled post came from, whose card holds the text boxes. */
  version: Version;
  scheduledPost: ScheduledPost;
  charLimit: number;
  onSaved: (scheduledPost: ScheduledPost) => void;
  onUnscheduled: () => void;
  onCancel: () => void;
}) {
  const [edit, setEdit] = useState<ScheduledPostEdit>(() => ({
    texts: scheduledPost.parts.map((part) => part.text),
    when: dateTimeOf(scheduledPost.publishAt),
    where: destinationDraftOf(scheduledPost),
  }));
  const { busy, error, save, unschedule } = useScheduledPostActions(scheduledPost);
  const changes = changesFrom(scheduledPost, edit);
  const total = scheduledPost.parts.length;

  const parts: ShownPart[] = scheduledPost.parts.map((part, i) => {
    const text = edit.texts[i] ?? '';
    return {
      text,
      charCount: xWeightedLength(text),
      charLimit,
      live: part.live,
      xPostUrl: part.xPostUrl,
    };
  });

  const setText = (index: number, text: string) =>
    setEdit((current) => ({
      ...current,
      texts: current.texts.map((t, i) => (i === index ? text : t)),
    }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!changes) return;
    const saved = await save(changes);
    if (saved) onSaved(saved);
  };

  const remove = async () => {
    if (await unschedule()) onUnscheduled();
  };

  return (
    // The API checks the time and the text, and its refusal shows in the panel.
    <form noValidate onSubmit={(e) => void submit(e)} className="space-y-6">
      <VersionCard
        version={version}
        parts={parts}
        renderText={(part, index) =>
          part.live ? undefined : (
            <Textarea
              aria-label={total > 1 ? `Part ${index + 1} text` : 'Post text'}
              value={part.text}
              onChange={(e) => setText(index, e.target.value)}
              rows={total > 1 ? 3 : 5}
              disabled={busy}
              className="font-sans text-[15px] leading-relaxed"
            />
          )
        }
      />
      <Panel name="Edit the Scheduled post">
        <p className="font-sans text-base font-semibold text-foreground">Edit the Scheduled post</p>
        <DateTimeFields
          value={edit.when}
          onChange={(when) => setEdit((current) => ({ ...current, when }))}
          disabled={busy}
        />
        <WhereField
          value={edit.where}
          onChange={(where) => setEdit((current) => ({ ...current, where }))}
          disabled={busy}
        />
        {error && <ErrorBanner message={error} />}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          <Button
            type="button"
            variant="ghost"
            className="h-10 text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => void remove()}
          >
            Unschedule
          </Button>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button type="button" variant="outline" className="h-10" onClick={onCancel}>
              Cancel
            </Button>
            <Button
              type="submit"
              className="h-10"
              disabled={busy || !changes || Object.keys(changes).length === 0}
            >
              Save changes
            </Button>
          </div>
        </div>
      </Panel>
    </form>
  );
}
