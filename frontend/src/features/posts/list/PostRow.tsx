import { useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronDown } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { InTheCommunity } from '@/features/scheduledPosts/InTheCommunity';
import { TIME_ZONE } from '@/features/scheduledPosts/localTime';
import { XLengthCounter } from '@/features/scheduledPosts/XLengthCounter';
import { xWeightedLength } from '@/lib/xLength';
import { cn } from '@/lib/utils';
import type { PostListItem, ScheduledPostSummary } from '@/services/postService';
import { formatWhen } from '../panels/panelFacts';
import { Facts } from '../panels/panelParts';
import { postTitle } from '../postStatus';
import { rowMoment, rowWhen } from './rowWhen';

/** X's limit for an account without Premium, when no X account is connected to say otherwise. */
const DEFAULT_CHAR_LIMIT = 280;

function Destination({ scheduledPost }: { scheduledPost: ScheduledPostSummary }) {
  return scheduledPost.community ? (
    <InTheCommunity community={scheduledPost.community} />
  ) : (
    <>Your profile</>
  );
}

function shape(post: PostListItem): string {
  return post.format === 'thread' ? `Thread · ${post.parts.length} Parts` : 'Single post';
}

/** What a row says under its title, by the Post's status. */
function rowFacts(post: PostListItem) {
  const scheduled = post.scheduledPost;
  const versions = `${post.versionCount} ${post.versionCount === 1 ? 'Version' : 'Versions'}`;
  if (!scheduled) return [shape(post), versions];
  const facts = [shape(post), <Destination key="destination" scheduledPost={scheduled} />];
  if (post.status === 'published' && scheduled.community && scheduled.shareWithFollowers) {
    facts.push('Shared with followers');
  }
  if (post.status === 'published' && scheduled.xPostUrl) {
    facts.push(
      <a
        key="x"
        href={scheduled.xPostUrl}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-foreground underline underline-offset-2"
      >
        View on X
      </a>,
    );
  }
  return facts;
}

function When({ iso }: { iso: string }) {
  const { day, date, time } = rowWhen(iso);
  return (
    <p className="w-20 shrink-0 font-sans text-xs leading-5 text-muted-foreground">
      <span className="block font-medium text-foreground">{day}</span>
      <span className="block">{date}</span>
      <span className="block font-mono tabular-nums">{time}</span>
    </p>
  );
}

/** Every Part with its length, then where and when it goes; the moment is in `TIME_ZONE`. */
function Expanded({ post, id, charLimit }: { post: PostListItem; id: string; charLimit: number }) {
  const scheduled = post.scheduledPost;
  const thread = post.parts.length > 1;
  return (
    <div id={id} className="space-y-3 pt-2">
      <ol className="space-y-2">
        {post.parts.map((text, i) => (
          <li
            key={i}
            aria-label={thread ? `Part ${i + 1} of ${post.parts.length}` : 'Post'}
            className="space-y-1 rounded-lg border border-border bg-background px-3 py-2"
          >
            <p className="whitespace-pre-wrap break-words font-sans text-sm text-foreground">
              {text}
            </p>
            <XLengthCounter length={xWeightedLength(text)} limit={charLimit} />
          </li>
        ))}
      </ol>
      {scheduled && (
        <Facts
          items={[
            <Destination key="destination" scheduledPost={scheduled} />,
            `${formatWhen(rowMoment(post))} (${TIME_ZONE})`,
          ]}
        />
      )}
    </div>
  );
}

/**
 * One Post in a Posts tab: its time, its title linking to the Post page, what it is, and on
 * expanding, every Part.
 */
export function PostRow({ post, charLimit }: { post: PostListItem; charLimit: number | null }) {
  const [expanded, setExpanded] = useState(false);
  const partsId = useId();
  const title = postTitle(post.parts[0] ?? post.brief) || 'Untitled Post';
  const scheduled = post.scheduledPost;

  return (
    <li aria-label={title} className="flex gap-4 px-4 py-4">
      <When iso={rowMoment(post)} />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-start gap-2">
          <Link
            to={`/posts/${post.id}`}
            className="min-w-0 flex-1 break-words font-sans text-sm font-medium text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm"
          >
            {title}
          </Link>
          {post.status === 'scheduled' && (
            <Badge variant={scheduled?.state === 'publishing' ? 'warning' : 'accent'}>
              {scheduled?.state === 'publishing' ? 'Publishing' : 'Scheduled'}
            </Badge>
          )}
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={expanded ? partsId : undefined}
            aria-label={expanded ? 'Hide the Parts' : 'Show every Part'}
            onClick={() => setExpanded((open) => !open)}
            className="-mr-2 -mt-1.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronDown
              aria-hidden
              className={cn('h-4 w-4 transition-transform', expanded && 'rotate-180')}
            />
          </button>
        </div>
        <Facts items={rowFacts(post)} />
        {post.status === 'failed' && scheduled?.failedReason && (
          <p title={scheduled.failedReason} className="truncate font-sans text-sm text-destructive">
            {scheduled.failedReason}
          </p>
        )}
        {expanded && (
          <Expanded post={post} id={partsId} charLimit={charLimit ?? DEFAULT_CHAR_LIMIT} />
        )}
      </div>
    </li>
  );
}
