import { MoreVertical } from 'lucide-react';
import { useProfile } from '@/pages/Home/ProfileContext';
import { UserMenu } from './UserMenu';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

export function UserCard() {
  const profile = useProfile();
  const display = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : 'Guest';
  const avatar = profile?.avatarUrl ?? null;

  return (
    <div className="flex h-16 items-center gap-3 border-t border-border px-3">
      <div className="relative flex h-9 w-9 items-center justify-center overflow-hidden rounded-full bg-primary-gradient-soft text-sm text-foreground ring-1 ring-inset ring-primary/25">
        {avatar ? (
          <img
            src={avatar}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <span className="bg-primary-gradient bg-clip-text text-transparent">
            {initials(display)}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col">
        <span className="truncate font-sans text-sm font-medium text-foreground">{display}</span>
      </div>
      <UserMenu
        trigger={
          <button
            type="button"
            aria-label="User menu"
            className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded text-muted-foreground hover:bg-muted"
          >
            <MoreVertical className="h-4 w-4" />
          </button>
        }
      />
    </div>
  );
}
