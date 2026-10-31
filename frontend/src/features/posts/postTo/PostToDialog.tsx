import { useState, type FormEvent, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { ThreadParts } from '@/components/ThreadParts';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { AllowanceNotice } from '@/features/billing/AllowanceNotice';
import { LowUsageWarning } from '@/features/billing/LowUsageWarning';
import { leftInTopUps } from '@/features/billing/usage';
import { useUsage } from '@/features/billing/useUsage';
import {
  destinationFrom,
  PROFILE_DRAFT,
  type DestinationDraft,
} from '@/features/scheduledPosts/communities';
import { X_BUSY_NOTICE } from '@/features/scheduledPosts/useCreateScheduledPost';
import { LiveOnX } from '@/features/scheduledPosts/LiveOnX';
import { XLengthCounter } from '@/features/scheduledPosts/XLengthCounter';
import { ConnectXPrompt } from '@/features/xConnection/ConnectXPrompt';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { formatCount } from '@/lib/characters';
import { hasLink, xWeightedLength } from '@/lib/xLength';
import { FORMAT_THREAD, type Format } from '@/services/postService';
import type { ScheduledPost } from '@/services/scheduledPostService';
import type { AllowanceUsage } from '@/services/usageService';
import { formatWhen } from '../panels/panelFacts';
import type { ShownPart } from '../shownText';
import type { PostToSender } from './postTo';
import { initialWhen, publishAtFrom, WhenField, type WhenDraft } from './WhenField';
import { WhereField } from './WhereField';

type Step =
  { kind: 'choose' } | { kind: 'confirm' } | { kind: 'busy'; scheduledPost: ScheduledPost };

function partCount(count: number): string {
  return `${count} ${count === 1 ? 'part' : 'parts'}`;
}

/** Parts `first` to `last`, by their numbers in the Thread. */
function partRange(first: number, last: number): string {
  return first === last ? `part ${first}` : `parts ${first} to ${last}`;
}

/**
 * What a retry of a Thread that failed partway does with its live Parts, or why the Text
 * can't retry it; null without live Parts.
 */
function liveNote(liveCount: number, total: number): { text: string; blocks: boolean } | null {
  if (liveCount === 0) return null;
  const first = partRange(1, liveCount);
  const live = `${first[0].toUpperCase()}${first.slice(1)} ${liveCount === 1 ? 'is' : 'are'} already on X`;
  if (liveCount >= total) {
    const after = liveCount === 1 ? 'it' : 'them';
    return {
      text: `${live}, and the text has no part after ${after}. Ask for more parts with feedback.`,
      blocks: true,
    };
  }
  const rest = partRange(liveCount + 1, total);
  const go = total - liveCount === 1 ? 'goes' : 'go';
  const to = liveCount === 1 ? 'it' : `part ${liveCount}`;
  return { text: `${live}, so only ${rest} ${go} out, as replies to ${to}.`, blocks: false };
}

/** Each Part not yet live over X's limit by X's count, as a sentence naming it. */
function overLimit(
  parts: ShownPart[],
  lengths: number[],
  limit: number,
  thread: boolean,
): string[] {
  return lengths.flatMap((length, i) => {
    const over = length - limit;
    if (over <= 0 || parts[i]?.live) return [];
    const what = thread ? `Part ${i + 1}` : 'The post';
    const characters = `${formatCount(over)} ${over === 1 ? 'character' : 'characters'}`;
    return [`${what} is ${characters} over X's ${formatCount(limit)}-character limit.`];
  });
}

/**
 * What the Parts about to go out with a link use of the link posts left, in the period and in
 * Top-ups; null without a link, or without a cap on them.
 */
function linkNote(linkCount: number, allowance: AllowanceUsage | null | undefined): string | null {
  const inPeriod = allowance?.linkXPosts.left;
  if (linkCount === 0 || !allowance || inPeriod === null || inPeriod === undefined) return null;
  const left = inPeriod + leftInTopUps(allowance, 'linkXPosts');
  const links = linkCount === 1 ? 'Contains a link' : 'Contains links';
  return `${links}: uses ${linkCount} of your ${left} link ${left === 1 ? 'post' : 'posts'}`;
}

const PART_TEXT = 'whitespace-pre-wrap break-words font-sans text-sm text-foreground';
const PARTS_BOX = 'max-h-72 space-y-3 overflow-y-auto rounded-lg bg-muted/50 p-3';

/**
 * Every Part in the order X publishes them, each counted against the limit. A live Part is
 * locked: it is on X already and only the Parts after it go out.
 */
function PartsToPost({
  parts,
  lengths,
  limit,
  thread,
}: {
  parts: ShownPart[];
  lengths: number[];
  limit: number;
  thread: boolean;
}) {
  if (!thread) {
    return (
      <div className={PARTS_BOX}>
        {parts.map((part, i) => (
          <div key={i} className="space-y-1.5">
            <p className={PART_TEXT}>{part.text}</p>
            <XLengthCounter length={lengths[i] ?? 0} limit={limit} />
          </div>
        ))}
      </div>
    );
  }
  return (
    <ThreadParts
      parts={parts}
      className={PARTS_BOX}
      aside={(part, number) =>
        part.live ? <LiveOnX number={number} xPostUrl={part.xPostUrl} /> : null
      }
    >
      {(part, number) =>
        part.live ? (
          <>
            <p className={`${PART_TEXT} text-muted-foreground`}>{part.text}</p>
            <p className="font-sans text-xs text-muted-foreground">
              Already on X, so it can’t change.
            </p>
          </>
        ) : (
          <>
            <p className={PART_TEXT}>{part.text}</p>
            <XLengthCounter length={lengths[number - 1] ?? 0} limit={limit} />
          </>
        )
      }
    </ThreadParts>
  );
}

/**
 * "Post to…": where (My profile or a Community) and when (Now or a time) the Post's Text goes
 * out. Now asks for a last yes over every Part, since it can't be undone. `sender` decides
 * what sending does, so a Failed Post can patch its Scheduled post through the same dialog.
 * `onDone` gets the Scheduled post once the dialog is through with it.
 */
export function PostToDialog({
  format,
  parts,
  sender,
  initialWhere = PROFILE_DRAFT,
  onClose,
  onDone,
}: {
  /** The Text's Format. */
  format: Format;
  /** The text that goes out, in order, after any Parts already live, which come first. */
  parts: ShownPart[];
  sender: PostToSender;
  initialWhere?: DestinationDraft;
  onClose: () => void;
  onDone: (scheduledPost: ScheduledPost) => void;
}) {
  const { connection } = useXConnectionContext();
  const { sending, error, allowanceUsedUp, send } = sender;
  const [step, setStep] = useState<Step>({ kind: 'choose' });
  const [where, setWhere] = useState<DestinationDraft>(initialWhere);
  const [when, setWhen] = useState<WhenDraft>(initialWhen);
  const publishAt = publishAtFrom(when);
  // The period the post would count against: the chosen time's, or now's for Post now.
  const { usage } = useUsage(publishAt);

  const liveCount = parts.filter((part) => part.live).length;
  const thread = format === FORMAT_THREAD || liveCount > 0;
  const live = liveNote(liveCount, parts.length);
  const toSend = parts.length - liveCount;
  const destination = destinationFrom(where);
  const lengths = parts.map((part) => xWeightedLength(part.text));
  const ready = connection && !connection.needsReconnect;
  const tooLong = ready ? overLimit(parts, lengths, connection.charLimit, thread) : [];
  const links = linkNote(
    parts.filter((part) => !part.live && hasLink(part.text)).length,
    usage?.allowance,
  );
  const refusal = allowanceUsedUp ? (
    <AllowanceNotice refusal={allowanceUsedUp} />
  ) : (
    error && <ErrorBanner message={error} />
  );
  const liveLine = live && (
    <p
      className={
        live.blocks
          ? 'font-sans text-sm font-medium text-destructive'
          : 'font-sans text-sm text-foreground'
      }
    >
      {live.text}
    </p>
  );

  const close = () => {
    if (step.kind === 'busy') onDone(step.scheduledPost);
    else onClose();
  };

  const sendNow = async () => {
    if (!destination) return;
    const outcome = await send(
      when.now
        ? { destination, when: { postNow: true } }
        : { destination, when: { postNow: false, publishAt: publishAt ?? '' } },
    );
    // A User who isn't Subscribed any more is on their way to the Paywall.
    if (outcome.kind === 'notSubscribed') {
      onClose();
    } else if (outcome.kind === 'created') {
      const { scheduledPost } = outcome;
      // Posted now but still waiting: X was busy, and the publisher retries.
      if (when.now && scheduledPost.state === 'scheduled') setStep({ kind: 'busy', scheduledPost });
      else onDone(scheduledPost);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    // The dialog renders inside the Feedback form in the React tree, and submit events follow it.
    e.stopPropagation();
    if (step.kind === 'choose' && when.now) setStep({ kind: 'confirm' });
    else void sendNow();
  };

  const facts = [
    thread ? 'Thread' : 'Single post',
    partCount(parts.length),
    ...(connection ? [`as @${connection.handle}`] : []),
  ].join(' · ');

  let body: ReactNode;
  let footer: ReactNode;
  const cancel = (
    <Button type="button" variant="outline" className="h-10" onClick={close}>
      Cancel
    </Button>
  );

  if (step.kind === 'busy') {
    body = <p className="font-sans text-sm text-foreground">{X_BUSY_NOTICE}</p>;
    footer = (
      <Button type="button" className="h-10" onClick={close}>
        Done
      </Button>
    );
  } else if (connection === undefined) {
    body = (
      <p role="status" className="font-sans text-sm text-muted-foreground">
        Checking your X connection…
      </p>
    );
    footer = cancel;
  } else if (!ready) {
    body = <ConnectXPrompt what="this post" showError />;
    footer = cancel;
  } else if (step.kind === 'confirm') {
    const target = destination?.community
      ? `from @${connection.handle} into the community ${destination.community.name ?? destination.community.id}`
      : `on @${connection.handle}`;
    body = (
      <>
        <p className="font-sans text-sm text-foreground">
          {!thread ? 'This goes' : toSend === 1 ? 'This part goes' : `These ${toSend} parts go`} out{' '}
          {target} straight away, in this order. Posting can&apos;t be undone.
        </p>
        {liveLine}
        <PartsToPost parts={parts} lengths={lengths} limit={connection.charLimit} thread={thread} />
        {refusal}
      </>
    );
    footer = (
      <>
        <Button
          type="button"
          variant="outline"
          className="h-10"
          disabled={sending}
          onClick={() => setStep({ kind: 'choose' })}
        >
          Back
        </Button>
        <Button type="submit" className="h-10" disabled={sending}>
          {sending ? 'Posting…' : 'Post now'}
        </Button>
      </>
    );
  } else {
    const unsendable =
      sending ||
      tooLong.length > 0 ||
      Boolean(live?.blocks) ||
      destination === null ||
      (!when.now && !publishAt);
    body = (
      <>
        {liveLine}
        <WhereField value={where} onChange={setWhere} disabled={sending} />
        <WhenField value={when} onChange={setWhen} disabled={sending} />
        {tooLong.map((problem) => (
          <p key={problem} className="font-sans text-sm font-medium text-destructive">
            {problem}
          </p>
        ))}
        {links && <p className="font-sans text-xs text-muted-foreground">{links}</p>}
        {!allowanceUsedUp && <LowUsageWarning allowance={usage?.allowance} count="xPosts" />}
        {refusal}
      </>
    );
    footer = (
      <>
        {cancel}
        <Button type="submit" className="h-10" disabled={unsendable}>
          {when.now
            ? 'Review and post'
            : publishAt
              ? `Schedule for ${formatWhen(publishAt)}`
              : 'Schedule'}
        </Button>
      </>
    );
  }

  return (
    <Dialog open onOpenChange={(open) => (open ? null : close())}>
      <DialogContent className="max-w-[560px] max-sm:h-fit">
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle className="font-sans text-base font-semibold tracking-tight">
              Post to…
            </DialogTitle>
            <DialogDescription className="font-sans tabular-nums">{facts}</DialogDescription>
          </DialogHeader>
          <div className="space-y-5 px-6 pb-6">{body}</div>
          <DialogFooter className="justify-end gap-2">{footer}</DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
