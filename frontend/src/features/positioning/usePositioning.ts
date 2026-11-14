import { useCallback, useEffect, useRef, useState } from 'react';
import { isSubscriptionNeeded } from '@/features/billing/subscriptionNeeded';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { positioningService } from '@/services/positioningService';
import { forgetDraft, keepDraft, keptDraft } from './keptDraft';

type Loading = 'loading' | 'failed' | 'loaded';

/** The backend's sentence for a draft it couldn't write, for a request that never got one. */
const NOT_DRAFTED =
  "We couldn't draft your positioning. Write it yourself, a few sentences is enough.";

/** True when the backend would find `text` blank: it drops what Postgres can't store, then trims. */
function isBlank(text: string): boolean {
  // Python strips the C0 separators and U+0085 too, which a JS trim() keeps.
  return [...text].every((ch) => ch <= '\x1f' || ch === '\x85' || /[\s\p{Cs}]/u.test(ch));
}

/**
 * The User's Positioning as they are editing it, loaded on mount, with save and draft. With
 * `draftOnOpen`, a User with no Positioning gets the kept draft, else a fresh one, as it loads.
 */
export function usePositioning({ draftOnOpen = false }: { draftOnOpen?: boolean } = {}) {
  const { refresh: refreshOnboarding } = useOnboarding();
  const [loading, setLoading] = useState<Loading>('loading');
  const [attempt, setAttempt] = useState(0);
  /** The text as last saved; empty until the User saves a Positioning. */
  const [saved, setSaved] = useState('');
  const [text, setText] = useState('');
  /** The text as of the last edit, which a save in flight can't see in its closure. */
  const latestText = useRef('');
  const [saving, setSaving] = useState(false);
  /** Why the last save or draft failed, until the next edit, save or draft. */
  const [error, setError] = useState<string | null>(null);
  /** True when that save failed because the server refused the text itself. */
  const [textRefused, setTextRefused] = useState(false);
  /** True from a save until the next edit. */
  const [justSaved, setJustSaved] = useState(false);
  /** False once the User has used up today's drafts. */
  const [canDraft, setCanDraft] = useState(true);
  const [drafting, setDrafting] = useState(false);
  /** True from a draft filling the textarea until the next edit, save or draft. */
  const [justDrafted, setJustDrafted] = useState(false);

  const draft = useCallback(async () => {
    const before = latestText.current;
    setDrafting(true);
    setError(null);
    setTextRefused(false);
    setJustDrafted(false);
    try {
      const drafted = await positioningService.draft();
      setCanDraft(drafted.canDraft);
      if (drafted.text === null) {
        setError(drafted.reason ?? NOT_DRAFTED);
      } else if (latestText.current === before) {
        setText(drafted.text);
        latestText.current = drafted.text;
        setJustSaved(false);
        setJustDrafted(true);
        if (draftOnOpen) keepDraft(drafted.text);
      }
    } catch (e) {
      if (isSubscriptionNeeded(e)) void refreshOnboarding();
      // The only 429 this request gets is the daily limit, which the button's own line explains.
      else if (errorStatus(e) === 429) setCanDraft(false);
      else setError(errorMessage(e, NOT_DRAFTED));
    } finally {
      setDrafting(false);
    }
  }, [draftOnOpen, refreshOnboarding]);

  useEffect(() => {
    let cancelled = false;
    positioningService
      .get()
      .then((positioning) => {
        if (cancelled) return;
        setSaved(positioning.text ?? '');
        setText(positioning.text ?? '');
        latestText.current = positioning.text ?? '';
        setCanDraft(positioning.canDraft);
        setLoading('loaded');
        if (!draftOnOpen || positioning.text !== null) return;
        const kept = keptDraft();
        if (kept !== null) {
          setText(kept);
          latestText.current = kept;
          setJustDrafted(true);
        } else if (positioning.canDraft) {
          // Same tick as the load, so the textarea never renders editable before the draft starts.
          void draft();
        }
      })
      .catch(() => !cancelled && setLoading('failed'));
    return () => {
      cancelled = true;
    };
  }, [attempt, draftOnOpen, draft]);

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
    setJustDrafted(false);
  }, []);

  /** Resolves true when the text in the textarea is what got saved. */
  const save = useCallback(async (): Promise<boolean> => {
    setSaving(true);
    setError(null);
    setTextRefused(false);
    setJustDrafted(false);
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
      if (draftOnOpen) forgetDraft();
      return latestText.current === positioning.text;
    } catch (e) {
      // A refusal for want of a Subscription sends the User to the Paywall, not to an error.
      if (isSubscriptionNeeded(e)) void refreshOnboarding();
      else {
        // FastAPI's 422 carries a list, not a sentence, so the panel says its own.
        const refused = errorStatus(e) === 422;
        setError(
          errorMessage(
            e,
            refused
              ? "That text can't be saved as your positioning. Change it and save again."
              : "Couldn't save your positioning. Try again.",
          ),
        );
        setTextRefused(refused);
      }
      return false;
    } finally {
      setSaving(false);
    }
  }, [text, draftOnOpen, refreshOnboarding]);

  /** Shows `message` where a failed save's reason goes. */
  const fail = useCallback((message: string) => setError(message), []);

  const idle = loading === 'loaded' && !saving && !drafting;
  const hasText = !isBlank(text);
  const canSave = idle && hasText && text.trim() !== saved;
  /** Counted in code points, as the backend's limit counts, so an emoji is one character. */
  const length = [...text].length;

  return {
    loading,
    reload,
    text,
    length,
    edit,
    save,
    saving,
    idle,
    hasText,
    canSave,
    fail,
    error,
    textRefused,
    justSaved,
    draft,
    drafting,
    canDraft,
    canRequestDraft: idle && canDraft,
    justDrafted,
  };
}
