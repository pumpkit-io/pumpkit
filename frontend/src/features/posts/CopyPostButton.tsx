import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { track } from '@/lib/analytics';

/** Copy post: every Part of the text on screen, in order, a blank line between Parts. */
export function CopyPostButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState('copied');
      track('post_final_copied');
    } catch {
      setState('failed');
    }
  };

  return (
    <>
      {state === 'failed' && (
        <span className="font-sans text-xs text-muted-foreground">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </span>
      )}
      <Button type="button" variant="outline" className="h-10 shrink-0" onClick={() => void copy()}>
        {state === 'copied' ? 'Copied' : 'Copy post'}
      </Button>
    </>
  );
}
