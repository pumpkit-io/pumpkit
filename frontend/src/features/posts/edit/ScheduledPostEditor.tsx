import { useMemo, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { destinationDraftOf } from '@/features/scheduledPosts/communities';
import { cn } from '@/lib/utils';
import { xWeightedLength } from '@/lib/xLength';
import type { ScheduledPost } from '@/services/scheduledPostService';
import { HoverLabel, HoverLabels } from '../HoverLabel';
import { scheduledPostMediaPlace } from '../media/mediaPlaces';
import { mediaWait, partMediaOf } from '../media/partMedia';
import { useTextMedia } from '../media/useTextMedia';
import { Panel } from '../panels/panelParts';
import { DateTimeFields, dateTimeOf } from '../postTo/WhenField';
import { WhereField } from '../postTo/WhereField';
import type { ShownPart } from '../shownText';
import { TextCard } from '../TextCard';
import { changesFrom, type ScheduledPostEdit } from './scheduledPostEdit';
import { useScheduledPostActions } from './useScheduledPostActions';

/**
 * A waiting Scheduled post edited in place; only its copy changes, never the Post's Text. Its
 * Media changes as soon as a file is attached or removed, so Cancel only drops the other edits.
 */
export function ScheduledPostEditor({
  postId,
  scheduledPost,
  charLimit,
  askToReconnect,
  onReconnectNeeded,
  onSaved,
  onUnscheduled,
  onCancel,
}: {
  postId: string;
  scheduledPost: ScheduledPost;
  charLimit: number;
  /** Set when X must be reconnected before Media: the media button asks instead of taking files. */
  askToReconnect: (() => void) | undefined;
  /** Called when the server refuses an upload until X is reconnected. */
  onReconnectNeeded: () => void;
  onSaved: (scheduledPost: ScheduledPost) => void;
  onUnscheduled: () => void;
  /** Hears the Scheduled post with the Media it holds now. */
  onCancel: (scheduledPost: ScheduledPost) => void;
}) {
  const [edit, setEdit] = useState<ScheduledPostEdit>(() => ({
    texts: scheduledPost.parts.map((part) => part.text),
    when: dateTimeOf(scheduledPost.publishAt),
    where: destinationDraftOf(scheduledPost),
  }));
  const { busy, error, save, unschedule } = useScheduledPostActions(scheduledPost);
  const changes = changesFrom(scheduledPost, edit);
  const total = scheduledPost.parts.length;
  const place = useMemo(
    () => scheduledPostMediaPlace(postId, scheduledPost.id),
    [postId, scheduledPost.id],
  );
  const media = useTextMedia(
    postId,
    scheduledPost.parts.map((part) => part.media),
    total,
    onReconnectNeeded,
    place,
  );

  const parts: ShownPart[] = scheduledPost.parts.map((part, i) => {
    const text = edit.texts[i] ?? '';
    return {
      text,
      charCount: xWeightedLength(text),
      charLimit,
      live: part.live,
      xPostUrl: part.xPostUrl,
      media: part.media,
    };
  });

  const setText = (index: number, text: string) =>
    setEdit((current) => ({
      ...current,
      texts: current.texts.map((t, i) => (i === index ? text : t)),
    }));

  const partMedia = partMediaOf(media, parts, askToReconnect);
  const waitingFor = mediaWait(parts, media);

  /** The Scheduled post with the Media its Parts not live hold now. */
  const withMediaNow = (): ScheduledPost => ({
    ...scheduledPost,
    parts: scheduledPost.parts.map((part, index) =>
      part.live
        ? part
        : {
            ...part,
            media: media
              .tilesOf(index)
              .flatMap((tile) => (tile.state === 'ready' && !tile.removing ? [tile.media] : [])),
          },
    ),
  });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!changes || waitingFor) return;
    const saved = await save(changes);
    if (saved) onSaved(saved);
  };

  const remove = async () => {
    if (await unschedule()) onUnscheduled();
  };

  return (
    // The API checks the time and the text, and its refusal shows in the panel.
    <form noValidate onSubmit={(e) => void submit(e)} className="space-y-6">
      <TextCard
        parts={parts}
        media={partMedia}
        renderText={(part, index) =>
          part.live ? undefined : (
            <Textarea
              aria-label={total > 1 ? `Part ${index + 1} text` : 'Post text'}
              value={part.text}
              onChange={(e) => setText(index, e.target.value)}
              onPaste={(e) => {
                const files = Array.from(e.clipboardData?.files ?? []);
                if (!files.length || e.clipboardData.getData('text/plain')) return;
                e.preventDefault();
                partMedia(index)?.onFiles?.(files, 'paste');
              }}
              rows={total > 1 ? 3 : 5}
              disabled={busy}
              className="font-sans text-[15px] leading-relaxed"
            />
          )
        }
      />
      <Panel name="Edit the scheduled post">
        <p className="font-sans text-base font-semibold text-foreground">Edit the scheduled post</p>
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
            <Button
              type="button"
              variant="outline"
              className="h-10"
              onClick={() => onCancel(withMediaNow())}
            >
              Cancel
            </Button>
            <HoverLabels>
              <HoverLabel label={waitingFor ?? ''} quiet={!waitingFor}>
                <Button
                  type="submit"
                  className={cn('h-10', waitingFor && 'cursor-not-allowed opacity-50')}
                  disabled={busy || !changes || Object.keys(changes).length === 0}
                  aria-disabled={waitingFor ? true : undefined}
                >
                  Save changes
                </Button>
              </HoverLabel>
            </HoverLabels>
          </div>
        </div>
      </Panel>
    </form>
  );
}
