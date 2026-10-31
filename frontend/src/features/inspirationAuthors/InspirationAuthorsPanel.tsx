import { useRef } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { LimitNotice } from '@/components/LimitNotice';
import { MAX_INSPIRATION_AUTHORS } from '@/services/inspirationAuthorService';
import { AuthorPicker } from './AuthorPicker';
import { PersonaSlots } from './PersonaSlots';
import { useInspirationAuthorsContext } from './useInspirationAuthorsContext';

export function InspirationAuthorsPanel() {
  const { authors, loadFailed, adding, refreshing, error, notice, add, refresh, remove } =
    useInspirationAuthorsContext();
  const searchRef = useRef<HTMLInputElement>(null);
  const taken = authors?.length ?? 0;

  return (
    <section aria-labelledby="inspiration-authors-heading" className="space-y-5">
      <div className="space-y-1">
        <h2
          id="inspiration-authors-heading"
          className="font-sans text-xl font-semibold tracking-[-0.015em] text-foreground"
        >
          How your posts sound
        </h2>
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
            refresh={{ refreshing, onRefresh: (handle) => void refresh(handle) }}
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
          {taken > 0 && taken < MAX_INSPIRATION_AUTHORS && (
            <p className="font-sans text-sm text-muted-foreground">
              More authors give a steadier style.
            </p>
          )}
        </>
      )}
    </section>
  );
}
