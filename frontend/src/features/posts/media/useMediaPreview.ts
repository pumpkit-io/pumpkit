import { useEffect, useState } from 'react';
import { mediaService } from '@/services/mediaService';

/** The stored preview at `previewUrl` as a local URL an `<img>` can show, or whether it failed. */
export function useMediaPreview(previewUrl: string | null): {
  url: string | null;
  failed: boolean;
} {
  const [shown, setShown] = useState<{ for: string; url: string | null; failed: boolean } | null>(
    null,
  );

  useEffect(() => {
    if (!previewUrl) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    mediaService.preview(previewUrl, controller.signal).then(
      (blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setShown({ for: previewUrl, url: objectUrl, failed: false });
      },
      () => {
        if (!controller.signal.aborted) setShown({ for: previewUrl, url: null, failed: true });
      },
    );
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewUrl]);

  if (!previewUrl || shown?.for !== previewUrl) return { url: null, failed: false };
  return { url: shown.url, failed: shown.failed };
}
