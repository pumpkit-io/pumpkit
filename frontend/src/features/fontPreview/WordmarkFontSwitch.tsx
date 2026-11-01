import { useEffect, useState } from 'react';
import { Switch } from '@/components/ui/switch';

const PREVIEW_CLASS = 'font-wordmark-preview';

/**
 * Experiment: compare the app's fonts with the wordmark's, then keep one. The class goes on
 * <html> so dialogs and popovers, which portal out of the layout, switch with the pages.
 */
export function WordmarkFontSwitch() {
  const [on, setOn] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle(PREVIEW_CLASS, on);
    return () => document.documentElement.classList.remove(PREVIEW_CLASS);
  }, [on]);

  return (
    <label className="fixed bottom-4 right-4 z-30 flex items-center gap-2 rounded-full border border-border bg-card px-3 py-2 text-sm shadow-sm">
      <Switch checked={on} onCheckedChange={setOn} />
      Wordmark font
    </label>
  );
}
