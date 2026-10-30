import type { ReactNode } from 'react';
import { UserAvatar } from '@/components/UserAvatar';
import { LiveOnX } from '@/features/scheduledPosts/LiveOnX';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';
import { useProfile } from '@/pages/layout/ProfileContext';
import type { ShownPart } from './shownText';

function PartCounter({ part }: { part: ShownPart }) {
  const over = part.charCount - part.charLimit;
  return (
    <div className="space-y-0.5 font-sans text-[13px] tabular-nums">
      <p className={over > 0 ? 'text-destructive' : 'text-muted-foreground'}>
        {formatCount(part.charCount)} / {formatCount(part.charLimit)}
      </p>
      {over > 0 && (
        <p className="font-medium text-destructive">
          {`${formatCount(over)} characters over X's ${formatCount(part.charLimit)}-character limit`}
        </p>
      )}
    </div>
  );
}

/** One Part drawn as an X post: who posts it, its place in the Thread, its text and count. */
function XPart({
  part,
  number,
  total,
  name,
  handle,
  avatarUrl,
  text,
  clearCorner,
}: {
  part: ShownPart;
  number: number;
  total: number;
  name: string;
  handle: string | null;
  avatarUrl: string | null;
  text?: ReactNode;
  /** Leaves room on the name line for the card's corner action. */
  clearCorner: boolean;
}) {
  const inThread = total > 1;
  return (
    <li
      aria-label={inThread ? `Part ${number} of ${total}` : 'Post'}
      className="flex gap-3 px-4 py-4 sm:px-5"
    >
      <UserAvatar name={name} avatarUrl={avatarUrl} />
      <div className="min-w-0 flex-1 space-y-2">
        <div
          className={cn('flex items-baseline gap-1.5 font-sans text-sm', clearCorner && 'pr-10')}
        >
          <span className="truncate font-semibold text-foreground">{name}</span>
          {handle && <span className="truncate text-muted-foreground">@{handle}</span>}
          {inThread && (
            <span className="ml-auto shrink-0 text-[13px] tabular-nums text-muted-foreground">
              {number}/{total}
            </span>
          )}
        </div>
        {text ?? (
          <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-6 text-foreground">
            {part.text}
          </p>
        )}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <PartCounter part={part} />
          {part.live && <LiveOnX number={number} xPostUrl={part.xPostUrl} />}
        </div>
      </div>
    </li>
  );
}

/** The Post's text drawn as the X posts it makes, one per Part. */
export function TextCard({
  parts,
  renderText,
  corner,
  header,
  busy = false,
}: {
  parts: ShownPart[];
  /** Replaces a Part's text, such as with a box to edit it in. */
  renderText?: (part: ShownPart, index: number) => ReactNode;
  /** At the card's top right, such as Copy. */
  corner?: ReactNode;
  /** A row above the Parts that stays put while they scroll, such as the Text's tools. */
  header?: ReactNode;
  /** Dims the Parts while Pumpkit rewrites the text. */
  busy?: boolean;
}) {
  const profile = useProfile();
  const { connection } = useXConnectionContext();
  const name = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'You';

  return (
    <article
      aria-label="Text"
      aria-busy={busy}
      className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground"
    >
      {corner && <div className="absolute right-2 top-2">{corner}</div>}
      {header}
      {/* Taller than the space it is given, only the Parts scroll, with the scrollbar in the card. */}
      <ol
        className={cn(
          'min-h-0 divide-y divide-border overflow-y-auto transition-opacity motion-reduce:transition-none',
          busy && 'opacity-60',
        )}
      >
        {parts.map((part, index) => (
          <XPart
            key={index}
            part={part}
            number={index + 1}
            total={parts.length}
            name={name}
            handle={connection?.handle ?? null}
            avatarUrl={profile?.avatarUrl ?? null}
            text={renderText?.(part, index)}
            clearCorner={!!corner && index === 0}
          />
        ))}
      </ol>
    </article>
  );
}
