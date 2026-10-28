import { Link } from 'react-router-dom';
import { useSubscribed } from '@/features/billing/useSubscribed';
import { useInstance } from '@/features/instance/useInstance';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { useProfile } from '@/pages/layout/ProfileContext';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

/** Who is signed in, which X account they post as and their Plan, as a link to Settings. */
export function UserCard() {
  const profile = useProfile();
  const { connection } = useXConnectionContext();
  const { subscribed, planName } = useSubscribed();
  const { sells_plans } = useInstance();
  const display = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'Guest';
  const avatarUrl = profile?.avatarUrl ?? null;
  const plan =
    !sells_plans || subscribed === null ? null : subscribed ? planName : 'No Subscription';
  const details = [connection ? `@${connection.handle}` : null, plan].filter(
    (detail): detail is string => detail !== null,
  );

  return (
    <Link
      to="/settings"
      aria-label={['Your account', display, ...details].join(', ')}
      className="flex h-16 shrink-0 items-center gap-3 border-t border-border px-3 transition-colors hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <span
        data-avatar
        aria-hidden
        className="relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary-gradient-soft text-sm text-foreground ring-1 ring-inset ring-primary/25"
      >
        {avatarUrl ? (
          <img
            src={avatarUrl}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <span className="bg-primary-gradient bg-clip-text text-transparent">
            {initials(display)}
          </span>
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate font-sans text-sm font-medium text-foreground">{display}</p>
        {details.length > 0 && (
          <p className="flex min-w-0 gap-1.5 font-sans text-xs text-muted-foreground">
            {details.map((detail, i) => (
              <span key={detail} className="truncate">
                {i > 0 && <span aria-hidden>· </span>}
                <span>{detail}</span>
              </span>
            ))}
          </p>
        )}
      </div>
    </Link>
  );
}
