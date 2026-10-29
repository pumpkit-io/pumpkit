import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { Button } from '@/components/ui/button';
import { CHOOSE_PLAN_PATH, trackChoosePlan } from '@/features/billing/choosePlan';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useMediaQuery } from '@/lib/useMediaQuery';
import { FEEDBACK_MAX_CHARS, type Format } from '@/services/postService';
import { Composer } from '../Composer';
import { Dock } from './Dock';
import type { FeedbackSending } from './feedback';

/**
 * The dock of a Draft or a Failed Post: Feedback on the Text, with "Post to…" in the composer's
 * corner. A failed send keeps the Feedback, so trying again is one click.
 */
export function FeedbackDock({
  name,
  reason,
  origin,
  format: textFormat,
  feedback: sending,
  postTo,
}: {
  name: string;
  /** Above everything else, such as why a Failed Post didn't go out. */
  reason?: ReactNode;
  origin: ReactNode;
  /** The Text's Format, where the toggle starts. */
  format: Format;
  feedback: FeedbackSending;
  postTo: ReactNode;
}) {
  const { subscribed } = useSubscribed();
  const phone = useMediaQuery('(max-width: 639px)');
  const [feedback, setFeedback] = useState('');
  const [format, setFormat] = useState<Format>(textFormat);
  const { isWriting, error, notice, onSend } = sending;
  const typed = feedback.trim();

  const send = async () => {
    if (await onSend(typed, format)) setFeedback('');
  };

  const gate =
    subscribed === false ? (
      <Button asChild variant="solid" className="h-10 shrink-0 rounded-full">
        <Link to={CHOOSE_PLAN_PATH} onClick={() => trackChoosePlan('post_feedback')}>
          Subscribe to write
        </Link>
      </Button>
    ) : undefined;

  return (
    <Dock
      name={name}
      above={
        (reason || error || notice) && (
          <div className="space-y-2">
            {reason}
            {error && (
              <ErrorBanner message={error} onRetry={typed ? () => void send() : undefined} />
            )}
            {notice && <LimitNotice message={notice} />}
          </div>
        )
      }
      origin={origin}
    >
      <Composer
        label="Feedback"
        placeholder="What should change?"
        value={feedback}
        onChange={setFeedback}
        format={format}
        onFormatChange={setFormat}
        maxLength={FEEDBACK_MAX_CHARS}
        sendLabel="Send Feedback"
        shortcutVerb="send"
        onSend={() => void send()}
        isWriting={isWriting}
        sendDisabled={subscribed !== true}
        gate={gate}
        trailingAction={postTo}
        maxRows={phone ? 5 : 8}
      />
    </Dock>
  );
}

/** The dock while the Post loads: the same shape, with nothing to use yet. */
export function LoadingDock() {
  return (
    <Dock name="Loading" origin={<div className="h-3 w-40 rounded-full bg-muted" />}>
      <Composer
        label="Feedback"
        placeholder="What should change?"
        value=""
        onChange={() => {}}
        format="post"
        onFormatChange={() => {}}
        maxLength={FEEDBACK_MAX_CHARS}
        sendLabel="Send Feedback"
        shortcutVerb="send"
        onSend={() => {}}
        disabled
      />
    </Dock>
  );
}
