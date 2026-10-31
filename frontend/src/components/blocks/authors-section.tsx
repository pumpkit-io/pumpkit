import { useRef, type CSSProperties } from 'react';
import authors from '../../../public/assets/authors/authors.json';
import { track } from '@/lib/analytics';
import { useOnceVisible } from '@/lib/useOnceVisible';

type Author = { handle: string; name: string; photo: string };

// Copies of each account's X photo served by the Instance, so the page never requests anything from X.
const AUTHORS: readonly Author[] = authors.map(({ handle, name }) => ({
  handle,
  name,
  photo: `/assets/authors/${handle}.webp`,
}));

const ROW_LENGTH = 10;

const ROWS: readonly { authors: readonly Author[]; seconds: number; reverse: boolean }[] = [
  { authors: AUTHORS.slice(0, ROW_LENGTH), seconds: 46, reverse: false },
  { authors: AUTHORS.slice(ROW_LENGTH, 2 * ROW_LENGTH), seconds: 54, reverse: true },
  { authors: AUTHORS.slice(2 * ROW_LENGTH), seconds: 50, reverse: false },
];

// Each track holds three copies and scrolls by one third, so the loop has no seam.
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
      <div className="mx-auto flex max-w-5xl items-center justify-center gap-4 px-6">
        <h2
          id="authors-heading"
          className="text-balance text-center font-display text-2xl font-semibold tracking-tight md:text-3xl"
        >
          Write in the style of accounts like these.
        </h2>
      </div>

      <div className="mt-12 flex flex-col gap-4 md:mt-16 md:gap-5">
        {ROWS.map((row, index) => (
          <div key={index} className="landing-marquee overflow-hidden">
            <div
              className="landing-marquee-track flex w-max"
              style={
                {
                  '--marquee-duration': `${row.seconds}s`,
                  animationDirection: row.reverse ? 'reverse' : 'normal',
                } as CSSProperties
              }
            >
              {Array.from({ length: REEL_COPIES }, (_, copy) => (
                <ul
                  key={copy}
                  aria-hidden={copy === 0 ? undefined : true}
                  className="flex shrink-0 items-center gap-4 pr-4 md:gap-5 md:pr-5"
                >
                  {row.authors.map((author) => (
                    <li key={author.handle} className="shrink-0">
                      <img
                        src={author.photo}
                        alt={author.name}
                        width={96}
                        height={96}
                        loading="lazy"
                        decoding="async"
                        draggable={false}
                        className="size-14 rounded-full border border-border bg-muted object-cover md:size-16"
                      />
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
