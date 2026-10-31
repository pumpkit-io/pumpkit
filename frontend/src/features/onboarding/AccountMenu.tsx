import { ChevronDown } from 'lucide-react';
import { UserAvatar } from '@/components/UserAvatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '@/contexts/AuthContext';
import type { UserProfile } from '@/services/userService';

/** Who is signed in, with Sign out, for the pages before Pumpkit opens. */
export function AccountMenu({ profile }: { profile: UserProfile | null }) {
  const { logout } = useAuth();
  const name = profile
    ? [profile.firstName, profile.lastName].filter(Boolean).join(' ') || profile.email
    : '';

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Your account"
        className="flex shrink-0 items-center gap-1 rounded-full p-0.5 transition-colors hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <UserAvatar
          name={name}
          avatarUrl={profile?.avatarUrl ?? null}
          className="h-8 w-8 text-xs"
        />
        <ChevronDown aria-hidden className="h-4 w-4 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {profile && (
          <>
            <DropdownMenuLabel className="truncate font-normal">{profile.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuItem onSelect={() => void logout()}>Sign out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
