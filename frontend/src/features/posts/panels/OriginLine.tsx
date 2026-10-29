import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Version } from '@/services/postService';

const LINE = 'font-sans text-[13px] tabular-nums text-muted-foreground';

/**
 * Where the Text came from, cut to one line: "V3 · From Feedback: “…”" or "V1 · From your
 * Brief". It opens the full Brief or Feedback above it, since the line rarely holds all of it.
 */
export function OriginLine({
  brief,
  version,
  edited,
  writing,
}: {
  brief: string;
  /** The Version the Text came from. */
  version: Version;
  edited: boolean;
  /** The number of the Version being written from Feedback, if one is. */
  writing?: number | null;
}) {
  if (writing) {
    return <p className={`truncate ${LINE}`}>Writing Version {writing} from your Feedback…</p>;
  }

  const from = version.feedback
    ? `From Feedback: “${version.feedback.replace(/\s+/g, ' ').trim()}”`
    : 'From your Brief';
  const line = [`V${version.number}`, from, ...(edited ? ['edited'] : [])].join(' · ');

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={`block w-full truncate rounded-sm text-left transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${LINE}`}
        >
          {line}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        aria-label={version.feedback ? 'Feedback' : 'Brief'}
        className="max-h-[50vh] w-[min(36rem,calc(100vw-2rem))] overflow-y-auto"
      >
        <p className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-foreground">
          {version.feedback ?? brief}
        </p>
      </PopoverContent>
    </Popover>
  );
}
