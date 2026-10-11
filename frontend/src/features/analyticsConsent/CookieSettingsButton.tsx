import { openCookieSettings } from '@/lib/analyticsConsent';

/** Reopens the consent banner. A button, not a link: it changes a choice instead of going somewhere. */
export function CookieSettingsButton({ className }: { className?: string }) {
  return (
    <button type="button" onClick={openCookieSettings} className={className}>
      Cookie settings
    </button>
  );
}
