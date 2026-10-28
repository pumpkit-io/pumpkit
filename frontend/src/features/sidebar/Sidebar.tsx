import { NavLink } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { useInspirationAuthorsContext } from '@/features/inspirationAuthors/useInspirationAuthorsContext';
import { LegalLinks } from '@/features/legal/LegalLinks';
import { cn } from '@/lib/utils';
import { MAX_INSPIRATION_AUTHORS } from '@/services/inspirationAuthorService';
import { SIDEBAR_PAGES } from './pages';
import { UserCard } from './UserCard';
import { useNewPost } from './useNewPost';
import { useSidebar } from './useSidebar';

const ROW = cn(
  'group flex h-10 items-center gap-3 rounded-lg px-3 font-sans text-sm text-muted-foreground transition-colors',
  'hover:bg-[var(--hover)] hover:text-foreground',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
  'aria-[current=page]:bg-[var(--hover)] aria-[current=page]:font-medium aria-[current=page]:text-foreground',
);

const LEGAL_LINK_CLASS =
  'rounded-sm underline-offset-4 transition-colors hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

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

export function Sidebar() {
  const { setMobileOpen } = useSidebar();
  const newPost = useNewPost();
  const { authors } = useInspirationAuthorsContext();
  const personaCount = authors?.length ?? null;

  return (
    <div className="flex h-full w-full flex-col bg-card">
      <div className="flex h-14 shrink-0 items-center px-4">
        <Brand size="sm" />
      </div>

      <nav aria-label="Main" className="flex flex-col gap-0.5 px-2 pt-2">
        {SIDEBAR_PAGES.map(({ path, label, icon: Icon }) => {
          const isPersona = path === '/persona';
          return (
            <NavLink
              key={path}
              to={path}
              className={ROW}
              aria-label={
                isPersona && personaCount !== null
                  ? `${label}, ${personaCount} of ${MAX_INSPIRATION_AUTHORS} Inspiration authors`
                  : undefined
              }
              onClick={(e) => {
                if (path === '/new') {
                  e.preventDefault();
                  newPost.start('sidebar');
                }
                setMobileOpen(false);
              }}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
              <span className="truncate">{label}</span>
              {isPersona && personaCount !== null && <PersonaCount count={personaCount} />}
            </NavLink>
          );
        })}
      </nav>

      <div className="flex-1" />

      {/* A new tab, because leaving the signed-in layout would drop the Post on screen. */}
      <LegalLinks
        newTab
        className="px-4 pb-3"
        listClassName="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
        linkClassName={LEGAL_LINK_CLASS}
      />
      <UserCard />
    </div>
  );
}
