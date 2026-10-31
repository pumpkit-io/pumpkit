import { useState, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { AllowanceNotice } from '@/features/billing/AllowanceNotice';
import { LowUsageWarning } from '@/features/billing/LowUsageWarning';
import { useUsage } from '@/features/billing/useUsage';
import { PHONE, useMediaQuery } from '@/lib/useMediaQuery';
import type { AllowanceUsedUp } from '@/services/apiErrors';
import { FEEDBACK_MAX_CHARS, type Format } from '@/services/postService';
import { Composer } from '../Composer';
import { Dock } from './Dock';

/** What the Feedback bar needs from `usePost`, for the Draft and Failed panels. */
export interface FeedbackSending {
  isWriting: boolean;
  error: string | null;
  notice: string | null;
  allowanceUsedUp: AllowanceUsedUp | null;
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
  const phone = useMediaQuery(PHONE);
  const [feedback, setFeedback] = useState('');
  const [format, setFormat] = useState<Format>(textFormat);
  // A restore, an undo or a rewrite that changes the Text's Format moves the toggle with it.
  const [formatFollowed, setFormatFollowed] = useState<Format>(textFormat);
  if (formatFollowed !== textFormat) {
    setFormatFollowed(textFormat);
    setFormat(textFormat);
  }
  const { isWriting, error, notice, allowanceUsedUp, onSend } = sending;
  const { usage, reload: reloadUsage } = useUsage();
  const typed = feedback.trim();

  const send = async () => {
    const sent = await onSend(typed, format);
    if (sent) setFeedback('');
    reloadUsage();
  };

  const low = !allowanceUsedUp && (
    <LowUsageWarning allowance={usage?.allowance} count="generations" />
  );

  return (
    <Dock
      name={name}
      notes={
        (reason || error || notice || allowanceUsedUp || restoreError || low) && (
          <div className="space-y-2">
            {low}
            {reason}
            {restoreError && <ErrorBanner message={restoreError} />}
            {error && (
              <ErrorBanner message={error} onRetry={typed ? () => void send() : undefined} />
            )}
            {notice && <LimitNotice message={notice} />}
            {allowanceUsedUp && <AllowanceNotice refusal={allowanceUsedUp} />}
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
