import { useId } from 'react';
import type { Version } from '@/services/postService';
import { VersionView } from './VersionView';

/** One Version under its number, with the Feedback that produced it when it came from Feedback. */
export function NumberedVersion({ version }: { version: Version }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="space-y-3">
      <h3 id={headingId} className="font-sans text-sm font-medium tabular-nums text-foreground">
        Version {version.number}
      </h3>
      {version.feedback !== null && (
        <div className="space-y-1">
          <p className="font-sans text-xs font-medium text-muted-foreground">Your Feedback</p>
          <p className="whitespace-pre-wrap break-words border-l-2 border-border pl-3 font-sans text-sm text-muted-foreground">
            {version.feedback}
          </p>
        </div>
      )}
      <VersionView version={version} />
    </section>
  );
}
