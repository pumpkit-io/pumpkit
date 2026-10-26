import { useId } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { xWeightedLength } from '@/lib/xLength';
import { LiveOnX } from './LiveOnX';
import { partDrafts, type PartDraft } from './partDrafts';
import { XLengthCounter } from './XLengthCounter';

function move(drafts: PartDraft[], from: number, to: number): PartDraft[] {
  const moved = [...drafts];
  const [draft] = moved.splice(from, 1);
  moved.splice(to, 0, draft);
  return moved;
}

/**
 * One text area per Part, with a counter each against `charLimit` (none while it is unknown).
 * A single Part is a single X post; adding a Part makes it a Thread, whose Parts can be moved
 * and removed. Live Parts, which open the list, are read-only and nothing moves above them.
 */
export function PartEditor({
  parts,
  onChange,
  charLimit,
  disabled,
  placeholder,
}: {
  parts: PartDraft[];
  onChange: (parts: PartDraft[]) => void;
  charLimit: number | null;
  disabled?: boolean;
  placeholder?: string;
}) {
  const id = useId();
  const liveCount = parts.filter((draft) => draft.live).length;
  const thread = parts.length > 1 || liveCount > 0;

  const setText = (index: number, text: string) =>
    onChange(parts.map((draft, i) => (i === index ? { ...draft, text } : draft)));

  return (
    <div className="space-y-3">
      {parts.map((draft, index) => {
        const number = index + 1;
        if (draft.live) {
          return (
            <div key={draft.key} className="space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-sans text-sm font-medium text-foreground">Part {number}</span>
                <LiveOnX number={number} xPostUrl={draft.xPostUrl} />
              </div>
              <p className="whitespace-pre-wrap break-words rounded-md bg-muted px-3 py-2 font-sans text-sm text-muted-foreground">
                {draft.text}
              </p>
            </div>
          );
        }
        const textId = `${id}-part-${draft.key}`;
        return (
          <div key={draft.key} className="space-y-1.5">
            {thread && (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor={textId} className="font-sans text-sm font-medium text-foreground">
                  Part {number}
                </label>
                <div className="flex gap-1">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Move Part ${number} up`}
                    disabled={disabled || index === liveCount}
                    onClick={() => onChange(move(parts, index, index - 1))}
                  >
                    Up
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Move Part ${number} down`}
                    disabled={disabled || index === parts.length - 1}
                    onClick={() => onChange(move(parts, index, index + 1))}
                  >
                    Down
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove Part ${number}`}
                    disabled={disabled}
                    onClick={() => onChange(parts.filter((_, i) => i !== index))}
                  >
                    Remove
                  </Button>
                </div>
              </div>
            )}
            {!thread && (
              <label htmlFor={textId} className="sr-only">
                Post text
              </label>
            )}
            <Textarea
              id={textId}
              value={draft.text}
              onChange={(e) => setText(index, e.target.value)}
              placeholder={index === 0 ? placeholder : undefined}
              rows={thread ? 3 : 5}
              disabled={disabled}
            />
            {charLimit !== null && (
              <XLengthCounter length={xWeightedLength(draft.text)} limit={charLimit} />
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => onChange([...parts, ...partDrafts([''])])}
      >
        Add a Part
      </Button>
    </div>
  );
}
