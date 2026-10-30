import { useState } from 'react';
import { cn } from '@/lib/utils';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

/**
 * A photo, or initials on the accent tint while it loads, when it fails, or when there is none.
 * Decorative: the name or handle sits beside it.
 */
export function UserAvatar({
  name,
  avatarUrl,
  className,
}: {
  name: string;
  avatarUrl: string | null;
  className?: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const shown = avatarUrl && avatarUrl !== failedUrl ? avatarUrl : null;
  return (
    <span
      aria-hidden
      className={cn(
        'relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary-gradient-soft text-sm text-foreground ring-1 ring-inset ring-primary/25',
        className,
      )}
    >
      <span className="bg-primary-gradient bg-clip-text text-transparent">{initials(name)}</span>
      {shown && (
        <img
          src={shown}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          draggable={false}
          onError={() => setFailedUrl(shown)}
        />
      )}
    </span>
  );
}
