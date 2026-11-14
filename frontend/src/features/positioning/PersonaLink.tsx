import { Link } from 'react-router-dom';

/** For the page header: a link to the Persona page, where the User edits their Positioning. */
export function PersonaLink() {
  return (
    <Link
      to="/persona"
      className="inline-flex h-8 shrink-0 items-center rounded-lg border border-border bg-card px-3 font-sans text-xs font-medium text-foreground transition-colors hover:bg-[var(--hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      Persona
    </Link>
  );
}
