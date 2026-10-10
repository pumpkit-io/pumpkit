import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

function waitingMessage(handle: string, waiting: number): string {
  if (waiting === 0) return `No Scheduled posts are waiting to go out on @${handle}.`;
  if (waiting === 1) {
    return `1 Scheduled post is waiting to go out on @${handle}. It will fail unless you connect @${handle} again before its time.`;
  }
  return `${waiting} Scheduled posts are waiting to go out on @${handle}. They will fail unless you connect @${handle} again before their time.`;
}

/** Asks before disconnecting X, saying how many Scheduled posts would then fail. */
export function DisconnectXDialog({
  open,
  handle,
  waiting,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  handle: string;
  /** Undefined while the count is being refreshed. */
  waiting: number | undefined;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onCancel())}>
      <DialogContent className="max-w-[480px] max-sm:h-auto">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Disconnect @{handle}?
          </DialogTitle>
          <DialogDescription className="font-sans">
            {waiting === undefined
              ? 'Checking for Scheduled posts waiting to go out…'
              : waitingMessage(handle, waiting)}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="justify-end gap-2">
          <Button variant="outline" className="h-10" onClick={onCancel}>
            Keep it
          </Button>
          <Button className="h-10" disabled={waiting === undefined} onClick={onConfirm}>
            Disconnect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
