import { useEffect, useRef } from 'react';
import { MoreVertical } from 'lucide-react';
import { useProfile } from '@/pages/Home/ProfileContext';
import { cn } from '@/lib/utils';
import { FADE } from './transitions';
import { UserMenu } from './UserMenu';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

/** The avatar stays put across collapse; the name and menu button fade in beside it. */
export function UserCard({ expanded }: { expanded: boolean }) {
  const profile = useProfile();
  const detailsRef = useRef<HTMLDivElement>(null);
  const display = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'Guest';
  const avatarUrl = profile?.avatarUrl ?? null;

  useEffect(() => {
    detailsRef.current?.toggleAttribute('inert', !expanded);
  }, [expanded]);

  const avatar = (
    <span
      data-avatar
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
  );

  return (
    // px-2.5 centres the avatar on the 56px rail, in line with the New Post icon.
    <div
      className={cn(
        'flex h-16 shrink-0 items-center gap-3 border-t px-2.5 transition-colors duration-200 motion-reduce:transition-none',
        expanded ? 'border-border' : 'border-transparent',
      )}
    >
      {expanded ? (
        avatar
      ) : (
        <UserMenu
          trigger={
            <button
              type="button"
              aria-label="User menu"
              className="rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {avatar}
            </button>
          }
        />
      )}
      <div
        ref={detailsRef}
        className={cn('flex min-w-0 flex-1 items-center gap-3', FADE)}
        style={{ opacity: expanded ? 1 : 0, pointerEvents: expanded ? 'auto' : 'none' }}
      >
        <span className="truncate font-sans text-sm font-medium text-foreground">{display}</span>
        <UserMenu
          trigger={
            <button
              type="button"
              aria-label="User menu"
              className="ml-auto inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-[var(--hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <MoreVertical className="h-4 w-4" />
            </button>
          }
        />
      </div>
    </div>
  );
}
