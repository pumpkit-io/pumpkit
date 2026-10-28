import { useId, type ReactNode } from 'react';
import { UserAvatar } from '@/components/UserAvatar';
import { Badge } from '@/components/ui/badge';
import { LiveOnX } from '@/features/scheduledPosts/LiveOnX';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { formatCount } from '@/lib/characters';
import { useProfile } from '@/pages/layout/ProfileContext';
import { FORMAT_THREAD, type Tell, type Version } from '@/services/postService';
import type { ShownPart } from './shownText';

function partCount(count: number): string {
  return `${count} ${count === 1 ? 'Part' : 'Parts'}`;
}

function TellsBadge({ tells }: { tells: Tell[] }) {
  if (tells.length === 0) return <Badge variant="success">No machine-written tells</Badge>;
  return (
    <Badge variant="warning">
      {tells.length} machine-written {tells.length === 1 ? 'tell' : 'tells'}
    </Badge>
  );
}

function TellList({ tells }: { tells: Tell[] }) {
  const headingId = useId();
  if (tells.length === 0) return null;
  return (
    <div className="space-y-2 border-t border-border px-4 py-3 sm:px-5">
      <h4 id={headingId} className="font-sans text-xs font-semibold text-foreground">
        Machine-written tells
      </h4>
      <ul aria-labelledby={headingId} className="flex flex-wrap gap-1.5">
        {tells.map((tell) => (
          <li
            key={tell.name}
            className="rounded-md border border-warning/40 bg-warning/10 px-2 py-1 font-sans text-xs text-warning"
          >
            {tell.description}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PartCounter({ part }: { part: ShownPart }) {
  const over = part.charCount - part.charLimit;
  return (
    <div className="space-y-0.5 font-mono text-xs tabular-nums">
      <p className={over > 0 ? 'text-destructive' : 'text-muted-foreground'}>
        {formatCount(part.charCount)} / {formatCount(part.charLimit)}
      </p>
      {over > 0 && (
        <p className="font-sans font-medium text-destructive">
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
}: {
  part: ShownPart;
  number: number;
  total: number;
  name: string;
  handle: string | null;
  avatarUrl: string | null;
  text?: ReactNode;
}) {
  const inThread = total > 1;
  return (
    <li
      aria-label={inThread ? `Part ${number} of ${total}` : 'Post'}
      className="flex gap-3 px-4 py-4 sm:px-5"
    >
      <UserAvatar name={name} avatarUrl={avatarUrl} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex items-baseline gap-1.5 font-sans text-sm">
          <span className="truncate font-semibold text-foreground">{name}</span>
          {handle && <span className="truncate text-muted-foreground">@{handle}</span>}
          {inThread && (
            <span className="ml-auto shrink-0 font-mono text-xs tabular-nums text-muted-foreground">
              {number}/{total}
            </span>
          )}
        </div>
        {text ?? (
          <p className="whitespace-pre-wrap break-words font-sans text-[15px] leading-relaxed text-foreground">
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

/**
 * A Version under its number, Format and Part count, with its text drawn as the X posts it
 * makes. `parts` is the text on screen (see `shownParts`), which may be its Scheduled post's.
 * `renderText` replaces a Part's text, as the inline edit does with a text box.
 */
export function VersionCard({
  version,
  parts,
  renderText,
}: {
  version: Version;
  parts: ShownPart[];
  renderText?: (part: ShownPart, index: number) => ReactNode;
}) {
  const headingId = useId();
  const profile = useProfile();
  const { connection } = useXConnectionContext();
  const name = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'You';

  return (
    <article
      aria-labelledby={headingId}
      className="overflow-hidden rounded-xl border border-border bg-card text-card-foreground"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-baseline gap-2">
          <h2 id={headingId} className="font-sans text-sm font-semibold tabular-nums">
            Version {version.number}
          </h2>
          <p className="font-sans text-xs text-muted-foreground">
            {version.format === FORMAT_THREAD ? 'Thread' : 'Single post'} ·{' '}
            {partCount(parts.length)}
          </p>
        </div>
        <TellsBadge tells={version.tells} />
      </div>
      <ol className="divide-y divide-border">
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
          />
        ))}
      </ol>
      <TellList tells={version.tells} />
    </article>
  );
}
