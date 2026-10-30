import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { Version } from '@/services/postService';
import type { TextSaveState } from '../useTextAutosave';

const LINE = 'font-sans text-[13px] tabular-nums text-muted-foreground';

/**
 * Where the Text came from, cut to one line: "V3 · From Feedback: “…”" or "V1 · From your
 * Brief". It opens the full Brief or Feedback below it, since the line rarely holds all of it.
 */
export function OriginLine({
  brief,
  version,
  edited,
  writing,
  save,
  rewritesDropped = false,
}: {
  brief: string;
  /** The Version the Text came from. */
  version: Version;
  edited: boolean;
  /** The number of the Version being written from Feedback, if one is. */
  writing?: number | null;
  /** How saving the User's edit is going; only a failure takes the line. */
  save?: TextSaveState;
  /** An edit just dropped rewrites from redo, which History still holds. */
  rewritesDropped?: boolean;
}) {
  if (writing) {
    return <p className={`truncate ${LINE}`}>Writing version {writing} from your feedback…</p>;
  }
  if (save?.kind === 'retrying' || save?.kind === 'refused') {
    return (
      <p
        className="truncate font-sans text-[13px] text-destructive"
        title={save.kind === 'refused' ? save.message : undefined}
      >
        {save.kind === 'retrying' ? 'Edit not saved. Retrying.' : `Edit not saved. ${save.message}`}
      </p>
    );
  }
  if (rewritesDropped) {
    return (
      <p className="truncate font-sans text-[13px] text-foreground">
        Newer rewrites are in history
      </p>
    );
  }

  const from = version.feedback
    ? `From feedback: “${version.feedback.replace(/\s+/g, ' ').trim()}”`
    : 'From your brief';
  const line = [`V${version.number}`, from, ...(edited ? ['edited'] : [])].join(' · ');

  // The Version number leads as a tag; the source gives way first when the line runs short.

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={line}
          className={`group flex w-full min-w-0 items-center gap-2 rounded-sm text-left transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${LINE}`}
        >
          <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs font-semibold text-foreground">
            V{version.number}
          </span>
          <span className="min-w-0 truncate">{from}</span>
          {edited && <span className="shrink-0">· edited</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
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
