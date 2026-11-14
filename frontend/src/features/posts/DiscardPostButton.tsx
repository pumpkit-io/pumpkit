import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { showToast } from '@/components/Toaster';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { track } from '@/lib/analytics';
import { errorMessage, errorStatus } from '@/services/apiErrors';
import { postService } from '@/services/postService';
import { HoverLabel } from './HoverLabel';
import { forgetDraft } from './list/recentDrafts';
import { ICON_BUTTON } from './panels/iconButton';

/**
 * Discard on a Draft, behind a confirmation. The Post and its Versions are deleted for good, so it
 * leaves Recently opened too; `onDiscarded` then moves the page on.
 */
export function DiscardPostButton({
  postId,
  from,
  label,
  icon = false,
  disabled = false,
  onDiscarded,
}: {
  postId: string;
  from: 'brief_page' | 'post_page';
  /** The accessible name, when "Discard" alone wouldn't say which post. */
  label?: string;
  /** A trash icon among the Post card's tools, inside `HoverLabels`, in place of the word. */
  icon?: boolean;
  disabled?: boolean;
  onDiscarded: () => unknown;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (busy) return;
    setOpen(false);
    setError(null);
  };

  const discard = async () => {
    setBusy(true);
    setError(null);
    try {
      await postService.discard(postId);
    } catch (e) {
      // A 404 means it was discarded already, from another tab or an AI app.
      if (errorStatus(e) !== 404) {
        setError(errorMessage(e, "Couldn't discard the post. Try again."));
        setBusy(false);
        return;
      }
    }
    forgetDraft(postId);
    track('post_discarded', { from });
    showToast('Discarded the post.');
    setBusy(false);
    setOpen(false);
    await onDiscarded();
  };

  return (
    <>
      {icon ? (
        <HoverLabel label="Discard post">
          <button
            type="button"
            aria-label={label ?? 'Discard'}
            disabled={disabled}
            onClick={() => setOpen(true)}
            className={ICON_BUTTON}
          >
            <Trash2 aria-hidden className="h-4 w-4" />
          </button>
        </HoverLabel>
      ) : (
        <Button
          type="button"
          variant="ghost"
          className="h-10"
          aria-label={label}
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          Discard
        </Button>
      )}
      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
        <DialogContent role="alertdialog" className="max-w-[480px] max-sm:h-fit">
          <DialogHeader>
            <DialogTitle className="font-sans text-base font-semibold tracking-tight">
              Discard this post?
            </DialogTitle>
            <DialogDescription className="font-sans">
              Its versions are deleted for good.
            </DialogDescription>
          </DialogHeader>
          {error && (
            <div className="px-6 pb-4">
              <ErrorBanner message={error} />
            </div>
          )}
          <DialogFooter className="justify-end gap-2">
            <Button variant="outline" className="h-10" disabled={busy} onClick={close}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              className="h-10"
              disabled={busy}
              onClick={() => void discard()}
            >
              {busy ? 'Discarding…' : 'Discard'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
