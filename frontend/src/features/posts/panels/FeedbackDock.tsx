import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { CHOOSE_PLAN_PATH, trackChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { PHONE, useMediaQuery } from '@/lib/useMediaQuery';
import { FEEDBACK_MAX_CHARS, type Format } from '@/services/postService';
import { Composer } from '../Composer';
import { Dock } from './Dock';

/** What the Feedback bar needs from `usePost`, for the Draft and Failed panels. */
export interface FeedbackSending {
  isWriting: boolean;
  error: string | null;
  notice: string | null;
  onSend: (feedback: string, format: Format) => Promise<boolean>;
}

/**
 * The dock of a Draft or a Failed Post: Feedback on the Text. A failed send keeps the Feedback,
 * so trying again is one click.
 */
export function FeedbackDock({
  name,
  reason,
  format: textFormat,
  feedback: sending,
  restoreError,
}: {
  name: string;
  /** Under the composer, such as why a Failed Post didn't go out. */
  reason?: ReactNode;
  /** The Text's Format, where the toggle starts. */
  format: Format;
  feedback: FeedbackSending;
  /** Why the last restore from History didn't happen. */
  restoreError?: string | null;
}) {
  const { subscribed } = useSubscribed();
  const phone = useMediaQuery(PHONE);
  const [feedback, setFeedback] = useState('');
  const [format, setFormat] = useState<Format>(textFormat);
  // A restore, an undo or a rewrite that changes the Text's Format moves the toggle with it.
  const [formatFollowed, setFormatFollowed] = useState<Format>(textFormat);
  if (formatFollowed !== textFormat) {
    setFormatFollowed(textFormat);
    setFormat(textFormat);
  }
  const { isWriting, error, notice, onSend } = sending;
  const typed = feedback.trim();

  const send = async () => {
    if (await onSend(typed, format)) setFeedback('');
  };

  const gate =
    subscribed === false ? (
      <Button asChild variant="solid" className="h-10 shrink-0">
        <Link to={CHOOSE_PLAN_PATH} onClick={() => trackChoosePlan('post_feedback')}>
          Subscribe to write
        </Link>
      </Button>
    ) : undefined;

  return (
    <Dock
      name={name}
      notes={
        (reason || error || notice || restoreError) && (
          <div className="space-y-2">
            {reason}
            {restoreError && <ErrorBanner message={restoreError} />}
            {error && (
              <ErrorBanner message={error} onRetry={typed ? () => void send() : undefined} />
            )}
            {notice && <LimitNotice message={notice} />}
          </div>
        )
      }
    >
      <Composer
        label="Feedback"
        placeholder="What should change?"
        value={feedback}
        onChange={setFeedback}
        format={format}
        onFormatChange={setFormat}
        maxLength={FEEDBACK_MAX_CHARS}
        sendLabel="Send feedback"
        sendOnEnter
        onSend={() => void send()}
        isWriting={isWriting}
        sendDisabled={subscribed !== true}
        gate={gate}
        maxRows={phone ? 5 : 8}
      />
    </Dock>
  );
}

/** The dock while the Post loads: the same shape, with nothing to use yet. */
export function LoadingDock() {
  return (
    <Dock name="Loading">
      <Composer
        label="Feedback"
        placeholder="What should change?"
        value=""
        onChange={() => {}}
        format="post"
        onFormatChange={() => {}}
        maxLength={FEEDBACK_MAX_CHARS}
        sendLabel="Send feedback"
        onSend={() => {}}
        disabled
      />
    </Dock>
  );
}
