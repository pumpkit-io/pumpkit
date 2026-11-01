import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';

/** A labelled value to copy, such as a secret, a URL or a command, with a Copy button. */
export function CopyRow({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: string;
  copyLabel: string;
}) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');

  useEffect(() => {
    if (state !== 'copied') return;
    const timer = window.setTimeout(() => setState('idle'), 2000);
    return () => window.clearTimeout(timer);
  }, [state]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setState('copied');
    } catch {
      setState('failed');
    }
  };

  return (
    <div className="space-y-1.5">
      <span className="font-sans text-xs font-medium text-muted-foreground">{label}</span>
      <div className="flex items-start gap-2">
        <code className="min-w-0 flex-1 select-all whitespace-pre-wrap break-all rounded-md bg-muted px-3 py-2 font-mono text-xs text-foreground">
          {value}
        </code>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-10 shrink-0"
          aria-label={copyLabel}
          onClick={() => void copy()}
        >
          {state === 'copied' ? 'Copied' : 'Copy'}
        </Button>
      </div>
      {state === 'failed' && (
        <p className="font-sans text-xs text-muted-foreground">
          Couldn&apos;t copy. Select the text and copy it yourself.
        </p>
      )}
    </div>
  );
}
