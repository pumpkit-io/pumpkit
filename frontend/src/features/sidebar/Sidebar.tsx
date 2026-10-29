import { NavLink } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { usePostCounts } from '@/features/posts/usePostCounts';
import { cn } from '@/lib/utils';
import { MAX_INSPIRATION_AUTHORS } from '@/services/inspirationAuthorService';
import { SIDEBAR_PAGES } from './pages';
import { UserCard } from './UserCard';
import { useNewPost } from './useNewPost';
import { useSidebar } from './useSidebar';

const ROW = cn(
  'group flex h-9 items-center gap-3 rounded-lg border border-transparent px-3 font-sans text-sm text-muted-foreground transition-colors',
  'hover:bg-[var(--hover)] hover:text-foreground',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
  'aria-[current=page]:border-border aria-[current=page]:bg-card aria-[current=page]:font-medium aria-[current=page]:text-foreground aria-[current=page]:shadow-raised',
);

/** "n/3" beside Persona, in the accent while the Persona is empty since nothing can be written yet. */
function PersonaCount({ count }: { count: number }) {
  return (
    <span
      aria-hidden
      className={cn(
        'ml-auto rounded-md px-1.5 py-0.5 font-mono text-xs tabular-nums',
        count === 0 ? 'bg-primary/15 text-primary' : 'text-muted-foreground',
      )}
    >
      {count}/{MAX_INSPIRATION_AUTHORS}
    </span>
  );
}

/** The Failed Posts beside Posts, in red, shown only while there are some to fix. */
function FailedCount({ count }: { count: number }) {
  return (
    <span
      aria-hidden
      className="ml-auto min-w-5 rounded-full bg-destructive px-1.5 py-0.5 text-center font-mono text-xs font-medium tabular-nums text-destructive-foreground"
    >
      {count}
    </span>
  );
}

function ariaLabel(path: string, label: string, personaCount: number | null, failed: number) {
  if (path === '/persona' && personaCount !== null) {
    return `${label}, ${personaCount} of ${MAX_INSPIRATION_AUTHORS} Inspiration authors`;
  }
  if (path === '/posts' && failed > 0) return `${label}, ${failed} Failed`;
  return undefined;
}

export function Sidebar() {
  const { setMobileOpen } = useSidebar();
  const newPost = useNewPost();
  const { authors } = useInspirationAuthorsContext();
  const personaCount = authors?.length ?? null;
  const failed = usePostCounts().counts?.failed ?? 0;

  return (
    <div className="flex h-full w-full flex-col bg-background">
      <div className="flex h-16 shrink-0 items-center px-5">
        <Brand size="sm" />
      </div>

      <nav aria-label="Main" className="flex flex-col gap-1 px-3 pt-1">
        {SIDEBAR_PAGES.map(({ path, label, icon: Icon }) => {
          const isPersona = path === '/persona';
          return (
            <NavLink
              key={path}
              to={path}
              className={ROW}
              aria-label={ariaLabel(path, label, personaCount, failed)}
              onClick={(e) => {
                if (path === '/new') {
                  e.preventDefault();
                  newPost.start('sidebar');
                }
                setMobileOpen(false);
              }}
            >
              <Icon
                className="h-[18px] w-[18px] shrink-0 group-aria-[current=page]:text-primary"
                aria-hidden
              />
              <span className="truncate">{label}</span>
              {isPersona && personaCount !== null && <PersonaCount count={personaCount} />}
              {path === '/posts' && failed > 0 && <FailedCount count={failed} />}
            </NavLink>
          );
        })}
      </nav>

      <div className="flex-1" />

      <UserCard />
    </div>
  );
}
