import { useRef } from 'react';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

// Placeholders until real X accounts are cleared for use (see #49, Out of Scope).
const AUTHORS: readonly string[] = Array.from({ length: 10 }, (_, i) => `[Author ${i + 1}]`);

// The track holds three copies and scrolls by one third, so the loop has no seam.
const REEL_COPIES = 3;

export function AuthorsSection() {
  const sectionRef = useRef<HTMLElement | null>(null);
  useOnceVisible(sectionRef, () => track('landing_authors_section_viewed'));

  return (
    <section
      ref={sectionRef}
      id="authors"
      aria-labelledby="authors-heading"
      className="scroll-mt-24 bg-background pb-16 pt-20 md:pb-32 md:pt-28"
    >
      <div className="mx-auto max-w-5xl px-6">
        <div className="text-center">
          <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Learn from the best on X
          </p>
          <h2
            id="authors-heading"
            className="mt-3 text-balance text-2xl font-semibold tracking-tight md:text-3xl"
          >
            Pick the authors whose style you want.
          </h2>
        </div>

        <div className="landing-marquee mt-12 overflow-hidden">
          <div className="landing-marquee-track flex w-max py-4">
            {Array.from({ length: REEL_COPIES }, (_, copy) => (
              <ul
                key={copy}
                aria-label={copy === 0 ? 'Authors' : undefined}
                aria-hidden={copy === 0 ? undefined : true}
                className="flex shrink-0 items-center gap-6 pr-6"
              >
                {AUTHORS.map((handle) => (
                  <li
                    key={handle}
                    className="flex shrink-0 items-center gap-2.5 rounded-full border border-border bg-card py-1.5 pl-1.5 pr-4"
                  >
                    <span aria-hidden className="size-8 shrink-0 rounded-full bg-muted" />
                    <span className="whitespace-nowrap text-sm font-medium text-muted-foreground">
                      {handle}
                    </span>
                  </li>
                ))}
              </ul>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
