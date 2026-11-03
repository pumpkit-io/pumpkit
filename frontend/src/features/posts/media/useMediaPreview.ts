import { useEffect, useState } from 'react';
import { mediaService } from '@/services/mediaService';

interface Fetched {
  url: string | null;
  failed: boolean;
}

/**
 * What `fetch` gives for `source` as a local URL, or whether it failed. A new source, or
 * unmounting, aborts the fetch and revokes the URL.
 */
function useObjectUrl(
  source: string | null,
  fetch: (source: string, signal: AbortSignal) => Promise<Blob>,
): Fetched {
  const [shown, setShown] = useState<{ for: string; url: string | null; failed: boolean } | null>(
    null,
  );

  useEffect(() => {
    if (!source) return;
    const controller = new AbortController();
    let objectUrl: string | null = null;
    fetch(source, controller.signal).then(
      (blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setShown({ for: source, url: objectUrl, failed: false });
      },
      () => {
        if (!controller.signal.aborted) setShown({ for: source, url: null, failed: true });
      },
    );
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [source, fetch]);

  if (!source || shown?.for !== source) return { url: null, failed: false };
  return { url: shown.url, failed: shown.failed };
}

/** The stored preview at `previewUrl` as a local URL an `<img>` can show, or whether it failed. */
export function useMediaPreview(previewUrl: string | null): Fetched {
  return useObjectUrl(previewUrl, mediaService.preview);
}

/** The whole file of the Media `mediaId` as a local URL, or whether it failed. */
export function useMediaFile(mediaId: string | null): Fetched {
  return useObjectUrl(mediaId, mediaService.file);
}
