import { cn } from '@/lib/utils';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
  return (first + last).toUpperCase() || '•';
}

/** The User's photo, or their initials on the accent tint. Decorative: the name sits beside it. */
export function UserAvatar({
  name,
  avatarUrl,
  className,
}: {
  name: string;
  avatarUrl: string | null;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'relative flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary-gradient-soft text-sm text-foreground ring-1 ring-inset ring-primary/25',
        className,
      )}
    >
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          draggable={false}
        />
      ) : (
        <span className="bg-primary-gradient bg-clip-text text-transparent">{initials(name)}</span>
      )}
    </span>
  );
}
