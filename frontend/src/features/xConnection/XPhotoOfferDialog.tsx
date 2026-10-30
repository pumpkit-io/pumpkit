import { useEffect, useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { UserAvatar } from '@/components/UserAvatar';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useInstance } from '@/features/instance/useInstance';
import { track } from '@/lib/analytics';
import { useProfileMutator } from '@/pages/layout/ProfileContext';
import { USE_X_PHOTO_FAILED } from './useXConnection';
import { useXConnectionContext } from './useXConnectionContext';

/** Asks a User with no Photo, once per X connection, whether to use the X account's photo. */
export function XPhotoOfferDialog() {
  const { app_name } = useInstance();
  const { connection, acceptPhoto, declinePhoto } = useXConnectionContext();
  const setProfile = useProfileMutator();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const photoUrl = connection?.offerPhoto ? connection.photoUrl : null;
  const open = photoUrl !== null;

  useEffect(() => {
    if (open) track('x_photo_offer_shown');
  }, [open]);

  const use = async () => {
    setSaving(true);
    setError(null);
    try {
      setProfile(await acceptPhoto());
      track('x_photo_offer_accepted');
    } catch {
      setError(USE_X_PHOTO_FAILED);
    } finally {
      setSaving(false);
    }
  };

  const notNow = () => {
    if (saving) return;
    track('x_photo_offer_declined');
    declinePhoto();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : notNow())}>
      <DialogContent className="max-w-[400px] max-sm:h-fit">
        <DialogHeader className="items-center pt-8 text-center sm:text-center">
          {photoUrl && (
            <UserAvatar
              name={connection?.handle ?? ''}
              avatarUrl={photoUrl}
              className="mb-4 h-24 w-24 text-2xl"
            />
          )}
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Use your X photo?
          </DialogTitle>
          <DialogDescription className="max-w-[17rem] font-sans">
            It will show next to your name in {app_name}. You can change it in Settings.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <div className="px-6 pb-4">
            <ErrorBanner message={error} />
          </div>
        )}
        <DialogFooter className="justify-end gap-2">
          <Button variant="outline" className="h-10" disabled={saving} onClick={notNow}>
            Not now
          </Button>
          <Button className="h-10" disabled={saving} onClick={() => void use()}>
            {saving ? 'Using photo…' : 'Use photo'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
