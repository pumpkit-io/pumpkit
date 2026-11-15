import { useCallback, useEffect, useRef, useState } from 'react';
import { isSubscriptionNeeded } from '@/features/billing/subscriptionNeeded';
import { useOnboarding } from '@/features/onboarding/useOnboarding';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { positioningService, type PositioningDraft } from '@/services/positioningService';

type Loading = 'loading' | 'failed' | 'loaded';

/** How often the step reads a running draft. */
export const DRAFT_POLL_MS = 2000;

/** Reads of a running draft that may fail in a row before the step stops waiting for it. */
export const DRAFT_READ_FAILURES_TOLERATED = 5;

/** The backend's sentence for a draft it couldn't write, for a request that never got one. */
const NOT_DRAFTED =
  "We couldn't draft your positioning. Write it yourself, a few sentences is enough.";

/** True when the backend would find `text` blank: it drops what Postgres can't store, then trims. */
function isBlank(text: string): boolean {
  // Python strips the C0 separators and U+0085 too, which a JS trim() keeps.
  return [...text].every((ch) => ch <= '\x1f' || ch === '\x85' || /[\s\p{Cs}]/u.test(ch));
}

/**
 * The User's Positioning as they are editing it, loaded on mount, with save. A User with no
 * Positioning gets the draft the server keeps, waiting while it runs (ADR 0030). With
 * `draftOnOpen`, a User with no draft, or a failed one, starts one.
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
  /** Why the last save failed, until the next edit or save. */
  const [error, setError] = useState<string | null>(null);
  /** True when that save failed because the server refused the text itself. */
  const [textRefused, setTextRefused] = useState(false);
  /** True from a save until the next edit. */
  const [justSaved, setJustSaved] = useState(false);
  /** True while the textarea waits for a draft. */
  const [drafting, setDrafting] = useState(false);
  /** Why there is no draft, once it failed. */
  const [draftReason, setDraftReason] = useState<string | null>(null);
  /** True once a draft filled the textarea. */
  const [drafted, setDrafted] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const fill = (next: string) => {
      setText(next);
      latestText.current = next;
    };

    /** Reads the positioning, letting a few reads in a row fail: the draft runs on regardless. */
    const read = async () => {
      for (let failures = 1; ; failures++) {
        try {
          return await positioningService.get();
        } catch (e) {
          if (cancelled || isSubscriptionNeeded(e) || failures >= DRAFT_READ_FAILURES_TOLERATED) {
            throw e;
          }
        }
        await new Promise((resolve) => setTimeout(resolve, DRAFT_POLL_MS));
        if (cancelled) throw new Error('cancelled');
      }
    };

    /** Follows the draft until it is ready or failed, starting one at most once. */
    const follow = async (first: PositioningDraft | null, mayStart: boolean) => {
      let draft = first;
      let started = false;
      try {
        for (;;) {
          if (draft?.state === 'ready' && draft.text !== null) {
            fill(draft.text);
            setDrafted(true);
            break;
          }
          if (draft?.state === 'running') {
            await new Promise((resolve) => setTimeout(resolve, DRAFT_POLL_MS));
          } else if (mayStart && !started) {
            started = true;
            await positioningService.startDraft();
          } else {
            setDraftReason(draft?.reason ?? null);
            break;
          }
          if (cancelled) return;
          const positioning = await read();
          if (cancelled) return;
          // Saved meanwhile, in another tab or on another device.
          if (positioning.text !== null) {
            setSaved(positioning.text);
            fill(positioning.text);
            break;
          }
          draft = positioning.draft;
        }
      } catch (e) {
        if (cancelled) return;
        if (isSubscriptionNeeded(e)) void refreshOnboarding();
        setDraftReason(NOT_DRAFTED);
      }
      if (!cancelled) setDrafting(false);
    };

    positioningService
      .get()
      .then((positioning) => {
        if (cancelled) return;
        setSaved(positioning.text ?? '');
        fill(positioning.text ?? '');
        setDraftReason(null);
        setDrafted(false);
        setLoading('loaded');
        if (positioning.text !== null) return;
        const draft = positioning.draft;
        const mayStart = draftOnOpen && (draft === null || draft.state === 'failed');
        // Same tick as the load, so the textarea never renders editable before the draft starts.
        setDrafting(draft?.state === 'running' || mayStart);
        void follow(draft, mayStart);
      })
      .catch(() => !cancelled && setLoading('failed'));
    return () => {
      cancelled = true;
    };
  }, [attempt, draftOnOpen, refreshOnboarding]);

  const reload = useCallback(() => {
    setLoading('loading');
    setAttempt((n) => n + 1);
  }, []);

  const edit = useCallback((next: string) => {
    setText(next);
    latestText.current = next;
    setJustSaved(false);
    setDrafted(false);
    setError(null);
    setTextRefused(false);
  }, []);

  /** Resolves true when the text in the textarea is what got saved. */
  const save = useCallback(async (): Promise<boolean> => {
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
  }, [text, refreshOnboarding]);

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
    drafting,
    draftReason,
    drafted,
  };
}
