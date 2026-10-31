import { forwardRef, useId, useMemo, useState, type KeyboardEvent } from 'react';
import { AtSign, Loader2, Search } from 'lucide-react';
import { UserAvatar } from '@/components/UserAvatar';
import { cn } from '@/lib/utils';
import { xPhotoAt } from '@/lib/xPhoto';
import { createAuthorSearch, type AuthorRow } from './authorMatches';
import { useAuthorDirectory } from './useAuthorDirectory';

const ROW_PHOTO_PX = 32;

interface AuthorPickerProps {
  /** Handles already in the Persona, which the list leaves out. */
  persona: string[];
  /** The handle being added; other picks wait for it. */
  adding: string | null;
  /** Every place in the Persona is taken. */
  full: boolean;
  /** Why the last pick was refused, shown under the field. */
  error: string | null;
  /** Resolves true once the author is in the Persona, which clears the search. */
  onPick: (handle: string, options: { lookup: boolean }) => Promise<boolean>;
}

function rowHandle(row: AuthorRow): string {
  return row.kind === 'lookup' ? row.handle : row.entry.handle;
}

/**
 * A combobox over the whole Author directory, searched in the browser, that also offers to look a
 * handle up on X (ADR 0019). It follows the ARIA 1.2 combobox pattern with a listbox popup.
 */
export const AuthorPicker = forwardRef<HTMLInputElement, AuthorPickerProps>(function AuthorPicker(
  { persona, adding, full, error, onPick },
  ref,
) {
  const directory = useAuthorDirectory();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const id = useId();
  const listId = `${id}-list`;
  const fullId = `${id}-full`;
  const errorId = `${id}-error`;

  const personaKey = persona.join(' ');
  const search = useMemo(
    () => createAuthorSearch(directory.entries ?? [], new Set(personaKey.split(' '))),
    [directory.entries, personaKey],
  );
  const rows = useMemo(() => search(query), [search, query]);
  const loading = directory.entries === null && !directory.failed;
  const expanded = open && !full;
  const activeIndex = rows.length ? Math.min(active, rows.length - 1) : -1;
  const optionId = (index: number) => `${id}-option-${index}`;

  const pick = async (row: AuthorRow) => {
    if (adding) return;
    if (await onPick(rowHandle(row), { lookup: row.kind === 'lookup' })) {
      setQuery('');
      setActive(0);
      setOpen(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!expanded) {
        setOpen(true);
        return;
      }
      const step = event.key === 'ArrowDown' ? 1 : -1;
      if (rows.length) setActive((activeIndex + step + rows.length) % rows.length);
    } else if (event.key === 'Enter') {
      if (!expanded || activeIndex < 0) return;
      event.preventDefault();
      void pick(rows[activeIndex]);
    } else if (event.key === 'Escape' && expanded) {
      event.preventDefault();
      setOpen(false);
    }
  };

  const describedBy = [full && fullId, error && errorId].filter(Boolean).join(' ') || undefined;
  const announcement =
    !expanded || loading
      ? ''
      : rows.length
        ? `${rows.length} ${rows.length === 1 ? 'result' : 'results'}`
        : 'No results';

  return (
    <div className="space-y-2">
      <label htmlFor={`${id}-field`} className="sr-only">
        Find an author
      </label>
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        />
        <input
          ref={ref}
          id={`${id}-field`}
          type="text"
          role="combobox"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={expanded && activeIndex >= 0 ? optionId(activeIndex) : undefined}
          aria-describedby={describedBy}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onClick={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
          placeholder="Search by name or @handle"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          disabled={full}
          className="flex h-12 w-full rounded-lg border border-input bg-card pl-10 pr-3 font-sans text-base text-foreground placeholder:text-muted-foreground focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60 sm:text-sm"
        />
      </div>

      {expanded && (
        <div className="overflow-hidden rounded-lg border border-border bg-card shadow-raised">
          {loading ? (
            <RowsSkeleton />
          ) : (
            <>
              {directory.failed && (
                <ListNote>
                  Couldn't load suggestions. You can still look up an @handle on X.
                </ListNote>
              )}
              {rows.length === 0 && !directory.failed && (
                <ListNote>
                  {query.trim()
                    ? 'No suggestion matches. Type an @handle to look it up on X.'
                    : 'Type a name or @handle to look someone up on X.'}
                </ListNote>
              )}
            </>
          )}
          <div
            id={listId}
            role="listbox"
            aria-label="Authors"
            className={cn('max-h-96 overflow-y-auto', (loading || rows.length === 0) && 'hidden')}
          >
            {!loading &&
              rows.map((row, index) => (
                <Row
                  key={`${row.kind}-${rowHandle(row)}`}
                  id={optionId(index)}
                  row={row}
                  active={index === activeIndex}
                  busy={adding === rowHandle(row)}
                  onHover={() => setActive(index)}
                  onPick={() => void pick(row)}
                />
              ))}
          </div>
        </div>
      )}

      {full && (
        <p id={fullId} className="font-sans text-sm text-muted-foreground">
          All three places are taken. Remove one to pick another.
        </p>
      )}
      <p
        id={errorId}
        aria-live="polite"
        className="font-sans text-sm text-destructive empty:hidden"
      >
        {error ?? ''}
      </p>
      <div role="status" aria-label="Results" className="sr-only">
        {announcement}
      </div>
    </div>
  );
});

function Row({
  id,
  row,
  active,
  busy,
  onHover,
  onPick,
}: {
  id: string;
  row: AuthorRow;
  active: boolean;
  busy: boolean;
  onHover: () => void;
  onPick: () => void;
}) {
  return (
    <div
      id={id}
      role="option"
      aria-selected={active}
      aria-busy={busy || undefined}
      // Keeps focus in the field, so the combobox stays open and keyboard-ready.
      onMouseDown={(event) => event.preventDefault()}
      onMouseMove={onHover}
      onClick={onPick}
      className={cn(
        'flex min-h-12 cursor-pointer items-center gap-3 px-3 py-2 font-sans text-sm',
        active && 'bg-muted',
      )}
    >
      {row.kind === 'directory' ? (
        <>
          <UserAvatar
            name={row.entry.name ?? row.entry.handle}
            avatarUrl={xPhotoAt(row.entry.photoUrl, ROW_PHOTO_PX)}
            className="h-8 w-8 text-xs"
          />
          <span className="min-w-0 flex-1 truncate">
            {row.entry.name && (
              <>
                <span className="font-medium text-foreground">{row.entry.name}</span>{' '}
              </>
            )}
            <span className="text-muted-foreground">@{row.entry.handle}</span>
          </span>
        </>
      ) : (
        <>
          <span
            aria-hidden
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-dashed border-primary/60 text-primary"
          >
            <AtSign className="h-4 w-4" />
          </span>
          <span className="min-w-0 flex-1 truncate text-foreground">
            Look up <span className="font-medium">@{row.handle}</span> on X
          </span>
        </>
      )}
      {busy && (
        <Loader2
          aria-hidden
          className="h-4 w-4 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
        />
      )}
    </div>
  );
}

function ListNote({ children }: { children: string }) {
  return (
    <p className="border-b border-border px-3 py-3 font-sans text-sm text-muted-foreground last:border-b-0">
      {children}
    </p>
  );
}

function RowsSkeleton() {
  return (
    <div role="status" aria-label="Loading suggestions" className="space-y-1 p-2">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="flex h-10 items-center gap-3 px-1">
          <span className="h-8 w-8 shrink-0 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
          <span className="h-3 w-1/2 animate-pulse rounded bg-muted motion-reduce:animate-none" />
        </div>
      ))}
    </div>
  );
}
