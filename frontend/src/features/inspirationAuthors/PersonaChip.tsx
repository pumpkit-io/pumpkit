import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Link } from 'react-router-dom';
import { UserAvatar } from '@/components/UserAvatar';
import { cn } from '@/lib/utils';
import type { InspirationAuthor } from '@/services/inspirationAuthorService';
import { useInspirationAuthorsContext } from './useInspirationAuthorsContext';

const CHIP =
  'inline-flex h-8 items-center gap-2 rounded-full border px-3 font-sans text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
const PHOTO_PX = 24;
const OVERLAP_PX = 8;
const MOTION = 'duration-200 ease-out motion-reduce:transition-none';

/** For the page header: whose style Pumpkit writes in, linking to the Persona page. */
export function PersonaChip() {
  const { authors } = useInspirationAuthorsContext();
  if (authors === null) return null;
  if (authors.length === 0) {
    return (
      <Link
        to="/persona"
        aria-label="Persona: empty, set it up"
        className={cn(CHIP, 'border-primary/40 text-primary transition-colors hover:bg-primary/10')}
      >
        <span className="shrink-0 font-medium text-foreground">Persona</span>
        <span>Set up</span>
      </Link>
    );
  }
  return <PhotoChip authors={authors} />;
}

/**
 * The photo stack, which unfolds leftward into photo and handle pairs on hover, keyboard focus or
 * a first tap. It overlays the title instead of widening, so the topbar never reflows.
 */
function PhotoChip({ authors }: { authors: InspirationAuthor[] }) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [tapped, setTapped] = useState(false);
  const expanded = hovered || focused || tapped;
  const chipRef = useRef<HTMLAnchorElement>(null);
  const tap = useRef({ touch: false, wasExpanded: false });

  useEffect(() => {
    if (!tapped && !focused) return;
    const collapseOnOutsideTap = (event: PointerEvent) => {
      if (chipRef.current?.contains(event.target as Node)) return;
      setTapped(false);
      setFocused(false);
    };
    document.addEventListener('pointerdown', collapseOnOutsideTap);
    return () => document.removeEventListener('pointerdown', collapseOnOutsideTap);
  }, [tapped, focused]);

  const handles = authors.map((author) => `@${author.handle}`);
  const restStackPx = PHOTO_PX + (authors.length - 1) * (PHOTO_PX - OVERLAP_PX);

  return (
    <div className="relative h-8 shrink-0">
      <span aria-hidden className={cn(CHIP, 'invisible border-transparent')}>
        <span className="font-medium">Persona</span>
        <span style={{ width: restStackPx }} />
      </span>
      <Link
        ref={chipRef}
        to="/persona"
        aria-label={`Persona: ${handles.join(', ')}`}
        onPointerEnter={(event) => event.pointerType === 'mouse' && setHovered(true)}
        onPointerLeave={(event) => event.pointerType === 'mouse' && setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        onPointerDown={(event) => {
          tap.current = { touch: event.pointerType !== 'mouse', wasExpanded: expanded };
        }}
        onClick={(event) => {
          if (tap.current.touch && !tap.current.wasExpanded) {
            event.preventDefault();
            setTapped(true);
          }
          tap.current = { touch: false, wasExpanded: false };
        }}
        className={cn(
          CHIP,
          'absolute right-0 top-0 z-10 max-w-[calc(100vw-4.5rem)] bg-card text-muted-foreground transition-colors md:max-w-[calc(100vw-2rem)]',
          expanded ? 'border-border text-foreground shadow-raised' : 'border-border',
        )}
      >
        {/* A phone lacks room for the label beside three handles; the accessible name keeps it. */}
        <span className={cn('shrink-0 font-medium text-foreground', expanded && 'max-sm:hidden')}>
          Persona
        </span>
        <span className="flex min-w-0 items-center">
          {authors.map((author, index) => (
            <span
              key={author.handle}
              className={cn('flex min-w-0 items-center transition-[margin]', MOTION)}
              style={{ marginLeft: index === 0 ? 0 : expanded ? 8 : -OVERLAP_PX }}
            >
              <span className="relative flex shrink-0 rounded-full bg-card ring-2 ring-card">
                <UserAvatar
                  name={author.handle}
                  avatarUrl={author.photoUrl}
                  className="h-6 w-6 text-[10px]"
                />
              </span>
              <span
                className={cn(
                  'min-w-0 truncate whitespace-nowrap transition-[max-width,opacity,margin]',
                  MOTION,
                )}
                style={handleStyle(expanded)}
              >
                {handles[index]}
              </span>
            </span>
          ))}
        </span>
      </Link>
    </div>
  );
}

// Inline so the collapsed state also holds where no stylesheet loads (the page tests).
function handleStyle(expanded: boolean): CSSProperties {
  return expanded
    ? { maxWidth: '9rem', opacity: 1, marginLeft: 4 }
    : { maxWidth: 0, opacity: 0, marginLeft: 0 };
}
