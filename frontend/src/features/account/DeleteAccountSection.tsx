import { useId, useState, type FormEvent } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { usePostCounts } from '@/features/posts/usePostCounts';
import { track } from '@/lib/analytics';
import { session } from '@/lib/session';
import { useProfile } from '@/pages/layout/ProfileContext';
import { errorMessage } from '@/services/apiErrors';
import { userService } from '@/services/userService';

/** The handle as the backend matches it: without "@", in any case. */
function normalizeHandle(handle: string): string {
  return handle.trim().replace(/^@/, '').toLowerCase();
}

/** What deleting takes away, from what Settings already loaded, each line only when it applies. */
function useLosses(): string[] {
  const waiting = usePostCounts().counts?.scheduled ?? 0;
  const losses: string[] = [];
  if (waiting > 0) losses.push('deletes your scheduled posts before they go out');
  losses.push('disconnects X and every connected AI app');
  return losses;
}

/** The last section of Settings: deleting the account at once, confirmed by typing the @handle. */
export function DeleteAccountSection() {
  const headingId = useId();
  const [open, setOpen] = useState(false);

  return (
    <section aria-labelledby={headingId} className="mt-4 space-y-3 border-t border-border pt-8">
      <div className="space-y-1">
        <h2 id={headingId} className="font-sans text-base font-semibold text-foreground">
          Delete account
        </h2>
        <p className="font-sans text-sm text-muted-foreground">
          Deletes your account and everything in it, and disconnects your X account.
        </p>
      </div>
      <Button
        type="button"
        variant="outline"
        className="h-10 text-destructive hover:text-destructive"
        onClick={() => setOpen(true)}
      >
        Delete account
      </Button>
      {open && <DeleteAccountDialog onClose={() => setOpen(false)} />}
    </section>
  );
}

function DeleteAccountDialog({ onClose }: { onClose: () => void }) {
  const handle = useProfile()?.xHandle ?? null;
  const losses = useLosses();
  const fieldId = useId();
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmed = handle !== null && normalizeHandle(typed) === normalizeHandle(handle);

  const close = () => {
    if (!busy) onClose();
  };

  const remove = async (event: FormEvent) => {
    event.preventDefault();
    if (!confirmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await userService.deleteAccount(typed);
    } catch (e) {
      setError(errorMessage(e, "Couldn't delete your account. Try again."));
      setBusy(false);
      return;
    }
    track('account_deleted');
    await session.end('account_deleted');
  };

  return (
    <Dialog open onOpenChange={(next) => !next && close()}>
      <DialogContent
        role="alertdialog"
        className="max-w-[480px] max-sm:h-fit"
        onEscapeKeyDown={(event) => busy && event.preventDefault()}
        onInteractOutside={(event) => busy && event.preventDefault()}
      >
        <form onSubmit={(event) => void remove(event)}>
          <DialogHeader>
            <DialogTitle className="font-sans text-base font-semibold tracking-tight">
              Delete your account?
            </DialogTitle>
            <DialogDescription className="font-sans">
              This can&apos;t be undone. Deleting your account:
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 px-6 pb-6 font-sans text-sm">
            <ul className="list-disc space-y-1 pl-5 text-foreground marker:text-muted-foreground">
              {losses.map((loss) => (
                <li key={loss}>{loss}</li>
              ))}
            </ul>
            <p className="text-muted-foreground">Posts already on X stay on X.</p>
            <div className="space-y-2">
              <label htmlFor={fieldId} className="block font-medium text-foreground">
                Type @{handle ?? '…'} to confirm
              </label>
              <Input
                id={fieldId}
                value={typed}
                onChange={(event) => setTyped(event.target.value)}
                disabled={busy || handle === null}
                autoComplete="off"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
              />
            </div>
            {error && <ErrorBanner message={error} />}
          </div>
          <DialogFooter className="justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              className="h-10"
              disabled={busy}
              onClick={close}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="destructive"
              className="h-10"
              disabled={!confirmed || busy}
            >
              {busy ? 'Deleting…' : 'Delete my account'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
