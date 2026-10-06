import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { SubscribePrompt } from '@/features/billing/SubscribePrompt';
import { FEEDBACK_MAX_CHARS } from '@/services/postService';
import { ErrorBanner } from './ErrorBanner';
import { LengthCounter } from './LengthCounter';
import { LimitNotice } from './LimitNotice';

interface FeedbackFormProps {
  subscribed: boolean | null;
  isWriting: boolean;
  error: string | null;
  notice: string | null;
  /** Resolves true once the new Version is on screen. */
  onSend: (feedback: string) => Promise<boolean>;
}

/** Feedback on the latest Version. A failed send keeps the text, so sending again is a retry. */
export function FeedbackForm({ subscribed, isWriting, error, notice, onSend }: FeedbackFormProps) {
  const [feedback, setFeedback] = useState('');
  const typed = feedback.trim();
  const canSend = subscribed === true && !!typed && feedback.length <= FEEDBACK_MAX_CHARS;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSend || isWriting) return;
    if (await onSend(typed)) setFeedback('');
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-3 border-t border-border pt-5">
      <div className="space-y-1.5">
        <label htmlFor="post-feedback" className="font-sans text-sm font-medium text-foreground">
          Feedback
        </label>
        <p id="post-feedback-hint" className="font-sans text-xs text-muted-foreground">
          Say what to change in the latest Final. Everything you don&apos;t mention stays as it is.
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
        <LengthCounter length={feedback.length} max={FEEDBACK_MAX_CHARS} />
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <LimitNotice message={notice} />}

      {subscribed === false ? (
        <SubscribePrompt message="Writing Posts needs a Subscription." source="home_feedback" />
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button type="submit" className="h-10 shrink-0" disabled={!canSend || isWriting}>
            {isWriting ? 'Writing…' : 'Send Feedback'}
          </Button>
          {isWriting && (
            <p role="status" className="font-sans text-sm text-muted-foreground">
              Writing the next Version. This can take a minute or two.
            </p>
          )}
        </div>
      )}
    </form>
  );
}
