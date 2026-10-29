import { Link } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { useInspirationAuthorsContext } from './useInspirationAuthorsContext';

/** For the page header: whose style Pumpkit writes in, linking to the Persona page. */
export function PersonaChip() {
  const { authors } = useInspirationAuthorsContext();
  if (authors === null) return null;
  const handles = authors.map((author) => `@${author.handle}`);
  const empty = handles.length === 0;

  return (
    <Link
      to="/persona"
      aria-label={empty ? 'Persona: empty, set it up' : `Persona: ${handles.join(', ')}`}
      className={cn(
        'inline-flex h-8 min-w-0 max-w-full items-center gap-2 rounded-full border px-3 font-sans text-xs transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        empty
          ? 'border-primary/40 text-primary hover:bg-primary/10'
          : 'border-border text-muted-foreground hover:bg-[var(--hover)] hover:text-foreground',
      )}
    >
      <span className="shrink-0 font-medium text-foreground">Persona</span>
      <span className="truncate">{empty ? 'Set up' : handles.join(' · ')}</span>
    </Link>
  );
}
