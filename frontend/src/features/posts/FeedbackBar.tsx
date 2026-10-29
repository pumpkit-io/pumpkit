import { useState, type FormEvent, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { charCount } from '@/lib/characters';
import { FEEDBACK_MAX_CHARS, type Format } from '@/services/postService';
import { FormatSelector } from './FormatSelector';
import { LengthCounter } from './LengthCounter';

interface FeedbackBarProps {
  isWriting: boolean;
  error: string | null;
  notice: string | null;
  /** Where the selector starts; the new Version then has the Format sent, so it stays in step. */
  latestFormat: Format;
  /** Resolves true once the new Version is in the Post. */
  onSend: (feedback: string, format: Format) => Promise<boolean>;
  /** Beside Rewrite, such as Copy post. */
  actions?: ReactNode;
}

/**
 * Feedback on the latest Version, for a Draft or a Failed Post. A failed send keeps the text,
 * so sending again is a retry.
 */
export function FeedbackBar({
  isWriting,
  error,
  notice,
  latestFormat,
  onSend,
  actions,
}: FeedbackBarProps) {
  const { subscribed } = useSubscribed();
  const [feedback, setFeedback] = useState('');
  const [format, setFormat] = useState<Format>(latestFormat);
  const typed = feedback.trim();
  const length = charCount(feedback);
  const canSend = subscribed === true && !!typed && length <= FEEDBACK_MAX_CHARS;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSend || isWriting) return;
    if (await onSend(typed, format)) setFeedback('');
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3">
      <div className="space-y-1.5">
        <label htmlFor="post-feedback" className="font-sans text-sm font-medium text-foreground">
          Feedback
        </label>
        <p id="post-feedback-hint" className="font-sans text-xs text-muted-foreground">
          Say what to change in the latest Version. Everything you don&apos;t mention stays as it
          is.
        </p>
        <Textarea
          id="post-feedback"
          aria-describedby="post-feedback-hint"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Shorter, and drop the last line."
          rows={3}
          disabled={isWriting}
          className="min-h-[5rem] resize-y leading-relaxed"
        />
        <LengthCounter length={length} max={FEEDBACK_MAX_CHARS} />
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <LimitNotice message={notice} />}
      {isWriting && (
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Writing the next Version. This can take a minute or two.
        </p>
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <FormatSelector value={format} onChange={setFormat} disabled={isWriting} />
        <div className="flex flex-wrap items-center gap-2 sm:ml-auto">
          {actions}
          {subscribed === false ? (
            <SubscribePrompt message="Writing Posts needs a Subscription." source="post_feedback" />
          ) : (
            <Button type="submit" className="h-10 shrink-0" disabled={!canSend || isWriting}>
              {isWriting ? 'Writing…' : 'Rewrite'}
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
