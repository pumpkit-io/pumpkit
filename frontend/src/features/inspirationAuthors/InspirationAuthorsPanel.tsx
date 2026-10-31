import { useId, useRef, type ReactNode } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { cn } from '@/lib/utils';
import { MAX_INSPIRATION_AUTHORS } from '@/services/inspirationAuthorService';
import { AuthorPicker } from './AuthorPicker';
import { PersonaSlots } from './PersonaSlots';
import { useInspirationAuthorsContext } from './useInspirationAuthorsContext';

/** The Persona step of Onboarding: the page's title, and its one action after the helper line. */
interface OnboardingStep {
  title: string;
  action: ReactNode;
}

/**
 * The Persona's slots and author picker. The Persona page shows it as a section with refresh
 * buttons; the Persona step as the whole page, quieter, ending in its action.
 */
export function InspirationAuthorsPanel({ step }: { step?: OnboardingStep }) {
  const { authors, loadFailed, adding, refreshing, error, notice, add, refresh, remove } =
    useInspirationAuthorsContext();
  const searchRef = useRef<HTMLInputElement>(null);
  const headingId = useId();
  const taken = authors?.length ?? 0;
  const Heading = step ? 'h1' : 'h2';
  // An empty Persona gets the hint only on the step, where Continue waits on it.
  const steadier = taken < MAX_INSPIRATION_AUTHORS && (taken > 0 || step !== undefined);

  return (
    <section aria-labelledby={headingId} className="space-y-5">
      <div className="space-y-1">
        <Heading
          id={headingId}
          className={cn(
            'font-sans font-semibold tracking-[-0.015em] text-foreground',
            step ? 'text-2xl/[30px]' : 'text-xl',
          )}
        >
          {step ? step.title : 'How your posts sound'}
        </Heading>
        <p className="font-sans text-sm text-muted-foreground">
          Up to three X accounts, your inspiration authors. Their recent posts set how your posts
          sound, never what they say.
        </p>
      </div>

      {loadFailed ? (
        <ErrorBanner message="Couldn't load your inspiration authors. Reload the page to try again." />
      ) : authors === null ? (
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading your inspiration authors…
        </p>
      ) : (
        <>
          <PersonaSlots
            authors={authors}
            adding={adding}
            onRemove={(handle) => void remove(handle)}
            onChooseEmpty={() => searchRef.current?.focus()}
            refresh={step ? undefined : { refreshing, onRefresh: (handle) => void refresh(handle) }}
          />
          <AuthorPicker
            ref={searchRef}
            persona={authors.map((author) => author.handle)}
            adding={adding}
            full={taken >= MAX_INSPIRATION_AUTHORS}
            error={error}
            onPick={(handle, { lookup }) => add(handle, { lookup })}
          />
          {notice && <LimitNotice message={notice} />}
          {(steadier || step) && (
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
              {steadier && (
                <p className="font-sans text-sm text-muted-foreground">
                  More authors give a steadier style.
                </p>
              )}
              {step && <div className="ml-auto">{step.action}</div>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
