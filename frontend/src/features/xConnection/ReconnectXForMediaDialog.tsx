import { useLocation } from 'react-router-dom';
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
import { useXConnectionContext } from './useXConnectionContext';

/**
 * Asks a User whose X connection predates X's media permission to reconnect X before
 * attaching Media, coming back to this page afterwards.
 */
export function ReconnectXForMediaDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { connection, busy, error, connect } = useXConnectionContext();
  const { pathname } = useLocation();
  const account = connection ? `@${connection.handle}` : 'your X account';
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-[480px] max-sm:h-fit">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Reconnect X to add media
          </DialogTitle>
          <DialogDescription className="font-sans">
            X needs your permission before Pumpkit can post images on {account}. Reconnect to give
            it, and you&apos;ll come back to this post.
          </DialogDescription>
        </DialogHeader>
        {error && <ErrorBanner message={error} />}
        <DialogFooter className="justify-end gap-2">
          <Button variant="outline" className="h-10" onClick={onClose}>
            Not now
          </Button>
          <Button className="h-10" disabled={busy} onClick={() => void connect(pathname)}>
            {busy ? 'Opening X…' : 'Reconnect X'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
