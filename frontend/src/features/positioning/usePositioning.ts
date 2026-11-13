import { useCallback, useEffect, useRef, useState } from 'react';
import { isSubscriptionNeeded } from '@/features/billing/subscriptionNeeded';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { positioningService } from '@/services/positioningService';

type Loading = 'loading' | 'failed' | 'loaded';

/** The User's Positioning as they are editing it, loaded on mount, with save. */
export function usePositioning() {
  const { refresh: refreshOnboarding } = useOnboarding();
  const [loading, setLoading] = useState<Loading>('loading');
  const [attempt, setAttempt] = useState(0);
  /** The text as last saved; empty until the User saves a Positioning. */
  const [saved, setSaved] = useState('');
  const [text, setText] = useState('');
  /** The text as of the last edit, which a save in flight can't see in its closure. */
  const latestText = useRef('');
  const [saving, setSaving] = useState(false);
  /** Why the last save failed, until the next edit or save. */
  const [error, setError] = useState<string | null>(null);
  /** True when that save failed because the server refused the text itself. */
  const [textRefused, setTextRefused] = useState(false);
  /** True from a save until the next edit. */
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    positioningService
      .get()
      .then((positioning) => {
        if (cancelled) return;
        setSaved(positioning?.text ?? '');
        setText(positioning?.text ?? '');
        latestText.current = positioning?.text ?? '';
        setLoading('loaded');
      })
      .catch(() => !cancelled && setLoading('failed'));
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setLoading('loading');
    setAttempt((n) => n + 1);
  }, []);

  const edit = useCallback((next: string) => {
    setText(next);
    latestText.current = next;
    setJustSaved(false);
    setError(null);
    setTextRefused(false);
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setTextRefused(false);
    try {
      const positioning = await positioningService.save(text);
      setSaved(positioning.text);
      // Text typed while the save was on its way stays, unsaved.
      if (latestText.current === text) {
        setText(positioning.text);
        latestText.current = positioning.text;
        setJustSaved(true);
      }
      track('positioning_saved');
    } catch (e) {
      // A refusal for want of a Subscription sends the User to the Paywall, not to an error.
      if (isSubscriptionNeeded(e)) void refreshOnboarding();
      else {
        setError(errorMessage(e, "Couldn't save your positioning. Try again."));
        setTextRefused(errorStatus(e) === 422);
      }
    } finally {
      setSaving(false);
    }
  }, [text, refreshOnboarding]);

  const trimmed = text.trim();
  const canSave = loading === 'loaded' && !saving && trimmed !== '' && trimmed !== saved;

  return { loading, reload, text, edit, save, saving, canSave, error, textRefused, justSaved };
}
