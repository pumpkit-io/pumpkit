import { useState } from 'react';
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
import type { ScheduledPost } from '@/services/scheduledPostService';

function CancelBody({
  onClose,
  onConfirm,
}: {
  onClose: () => void;
  onConfirm: () => Promise<string | null>;
}) {
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    setCancelling(true);
    setError(null);
    const refused = await onConfirm();
    setCancelling(false);
    if (refused) setError(refused);
    else onClose();
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-sans text-base font-semibold tracking-tight">
          Cancel this Scheduled post?
        </DialogTitle>
        <DialogDescription className="font-sans">
          It won&apos;t go out on X, and it is removed from your list.
        </DialogDescription>
      </DialogHeader>
      {error && (
        <div className="px-6 pb-4">
          <ErrorBanner message={error} />
        </div>
      )}
      <DialogFooter className="justify-end gap-2">
        <Button variant="outline" className="h-10" onClick={onClose}>
          Keep it
        </Button>
        <Button className="h-10" disabled={cancelling} onClick={() => void confirm()}>
          Cancel post
        </Button>
      </DialogFooter>
    </>
  );
}

/** Asks before cancelling a scheduled Scheduled post. */
export function CancelScheduledPostDialog({
  post,
  onClose,
  onConfirm,
}: {
  /** Null when closed. */
  post: ScheduledPost | null;
  onClose: () => void;
  onConfirm: () => Promise<string | null>;
}) {
  return (
    <Dialog open={post !== null} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-[480px] max-sm:h-auto">
        {post && <CancelBody key={post.id} onClose={onClose} onConfirm={onConfirm} />}
      </DialogContent>
    </Dialog>
  );
}
