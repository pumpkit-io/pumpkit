import { useState, type DragEvent, type ReactNode } from 'react';
import { UserAvatar } from '@/components/UserAvatar';
import { LiveOnX } from '@/features/scheduledPosts/LiveOnX';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { formatCount } from '@/lib/characters';
import { cn } from '@/lib/utils';
import { useProfile } from '@/pages/layout/ProfileContext';
import type { ShownPart } from './shownText';

/** What a Part that takes Media shows of it, and where files dropped or pasted on it go. */
export interface PartMedia {
  tiles: ReactNode;
  button: ReactNode;
  onFiles: (files: File[], via: 'drop' | 'paste') => void;
}

function carriesFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

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
  media,
  busy,
  clearCorner,
}: {
  part: ShownPart;
  number: number;
  total: number;
  name: string;
  handle: string | null;
  avatarUrl: string | null;
  text?: ReactNode;
  media: PartMedia | null;
  /** Dims the words while Pumpkit rewrites them; the Media stays as it is. */
  busy: boolean;
  /** Leaves room on the name line for the card's corner action. */
  clearCorner: boolean;
}) {
  const inThread = total > 1;
  const [dropping, setDropping] = useState(false);
  const dim = cn('transition-opacity motion-reduce:transition-none', busy && 'opacity-60');
  const dropTarget = media
    ? {
        onDragOver: (e: DragEvent) => {
          if (!carriesFiles(e)) return;
          e.preventDefault();
          setDropping(true);
        },
        onDragLeave: (e: DragEvent<HTMLLIElement>) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropping(false);
        },
        onDrop: (e: DragEvent) => {
          if (!carriesFiles(e)) return;
          e.preventDefault();
          setDropping(false);
          const files = Array.from(e.dataTransfer.files ?? []);
          if (files.length) media.onFiles(files, 'drop');
        },
      }
    : {};
  return (
    <li
      aria-label={inThread ? `Part ${number} of ${total}` : 'Post'}
      className={cn(
        'flex gap-3 px-4 py-4 transition-colors sm:px-5 motion-reduce:transition-none',
        dropping && 'bg-primary/5 ring-2 ring-inset ring-primary/50',
      )}
      {...dropTarget}
    >
      <UserAvatar name={name} avatarUrl={avatarUrl} />
      <div className="min-w-0 flex-1 space-y-2">
        <div
          className={cn(
            'flex items-baseline gap-1.5 font-sans text-sm',
            clearCorner && 'pr-10',
            dim,
          )}
        >
          <span className="truncate font-semibold text-foreground">{name}</span>
          {handle && <span className="truncate text-muted-foreground">@{handle}</span>}
          {inThread && (
            <span className="ml-auto shrink-0 text-[13px] tabular-nums text-muted-foreground">
              {number}/{total}
            </span>
          )}
        </div>
        <div className={dim}>
          {text ?? (
            <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-6 text-foreground">
              {part.text}
            </p>
          )}
        </div>
        {media?.tiles}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className={dim}>
            <PartCounter part={part} />
          </div>
          {part.live && <LiveOnX number={number} xPostUrl={part.xPostUrl} />}
          {media?.button}
        </div>
      </div>
    </li>
  );
}

/** The Post's text drawn as the X posts it makes, one per Part. */
export function TextCard({
  parts,
  renderText,
  media,
  corner,
  header,
  busy = false,
}: {
  parts: ShownPart[];
  /** Replaces a Part's text, such as with a box to edit it in. */
  renderText?: (part: ShownPart, index: number) => ReactNode;
  /** The Media on a Part that takes it; Parts with none show no media controls. */
  media?: (index: number) => PartMedia | null;
  /** At the card's top right, such as Copy. */
  corner?: ReactNode;
  /** A row above the Parts that stays put while they scroll, such as the Text's tools. */
  header?: ReactNode;
  /** Dims the Parts' words while Pumpkit rewrites the text. */
  busy?: boolean;
}) {
  const profile = useProfile();
  const { connection } = useXConnectionContext();
  const name = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'You';
  // Connected, the preview looks as the post will on X, with the X account's photo.
  const avatarUrl = connection ? connection.photoUrl : (profile?.avatarUrl ?? null);

  return (
    <article
      aria-label="Text"
      aria-busy={busy}
      className="relative flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card text-card-foreground"
    >
      {corner && <div className="absolute right-2 top-2">{corner}</div>}
      {header}
      {/* Taller than the space it is given, only the Parts scroll, with the scrollbar in the card. */}
      <ol className="min-h-0 divide-y divide-border overflow-y-auto">
        {parts.map((part, index) => (
          <XPart
            key={index}
            part={part}
            number={index + 1}
            total={parts.length}
            name={name}
            handle={connection?.handle ?? null}
            avatarUrl={avatarUrl}
            text={renderText?.(part, index)}
            media={media?.(index) ?? null}
            busy={busy}
            clearCorner={!!corner && index === 0}
          />
        ))}
      </ol>
    </article>
  );
}
