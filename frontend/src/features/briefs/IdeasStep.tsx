import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { splitIdeas, wholeBriefIdea, type Brief } from '@/services/briefService';
import type { AllowanceUsage } from '@/services/usageService';

export type IdeasChoice = 'each' | 'whole';

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? '' : 's'}`;

/**
 * The Ideas the planner found in a Brief, as a numbered checklist in posting order: the User ticks
 * the ones to write, or asks for one post covering everything, and sees what it costs first. A
 * Brief of one Idea shows only that Idea: planning left it unwritten for want of room.
 */
export function IdeasStep({
  brief,
  allowance,
  writing,
  onWrite,
  onEditBrief,
  children,
}: {
  brief: Brief;
  allowance: AllowanceUsage | null | undefined;
  writing: boolean;
  onWrite: (ideaIds: string[], choice: IdeasChoice) => void;
  onEditBrief: () => void;
  /** Why the last write didn't start, under the button. */
  children?: ReactNode;
}) {
  const ideas = splitIdeas(brief);
  const whole = wholeBriefIdea(brief);
  const single = ideas.length === 0;
  const [ticked, setTicked] = useState(() => new Set(ideas.map((idea) => idea.id)));
  const [choice, setChoice] = useState<IdeasChoice>('each');

  const picked =
    single || choice === 'whole'
      ? [whole.id]
      : ideas.filter((idea) => ticked.has(idea.id)).map((idea) => idea.id);
  const count = picked.length;
  const left = brief.generationsLeft;
  const short = left !== null && count > left;
  const canWrite = count > 0 && !short && !writing;

  const toggle = (ideaId: string) =>
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(ideaId)) next.delete(ideaId);
      else next.add(ideaId);
      return next;
    });

  return (
    <section aria-labelledby="ideas-step-line" className="space-y-5">
      <h2
        id="ideas-step-line"
        className="font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground"
      >
        {single
          ? 'We planned one post from your brief'
          : `We found ${ideas.length} ideas in your brief`}
      </h2>

      {single ? (
        <p className="max-w-[68ch] px-2 font-sans text-[15px] leading-6 text-foreground">
          {whole.plan?.coreIdea}
        </p>
      ) : (
        <>
          <fieldset disabled={choice === 'whole' || writing}>
            <legend className="sr-only">Ideas to write</legend>
            <ol
              className={cn(
                'max-w-[68ch] space-y-1',
                choice === 'whole' && 'opacity-50 motion-safe:transition-opacity',
              )}
            >
              {ideas.map((idea, index) => (
                <li key={idea.id}>
                  <label className="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2 hover:bg-muted/60 has-[:disabled]:cursor-default has-[:disabled]:hover:bg-transparent">
                    <input
                      type="checkbox"
                      checked={ticked.has(idea.id)}
                      onChange={() => toggle(idea.id)}
                      className="mt-1 h-4 w-4 shrink-0 accent-primary"
                    />
                    <span
                      aria-hidden
                      className="w-4 shrink-0 pt-px text-right font-sans text-[15px] tabular-nums text-muted-foreground"
                    >
                      {index + 1}
                    </span>
                    <span className="font-sans text-[15px] leading-6 text-foreground">
                      {idea.plan?.coreIdea}
                    </span>
                  </label>
                </li>
              ))}
            </ol>
          </fieldset>

          <div
            role="radiogroup"
            aria-label="How to write them"
            className="flex flex-wrap gap-x-6 gap-y-2 px-2 font-sans text-[15px] text-foreground"
          >
            {(
              [
                ['each', 'One post per idea'],
                ['whole', 'One post covering everything'],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="flex cursor-pointer items-center gap-2">
                <input
                  type="radio"
                  name="ideas-choice"
                  value={value}
                  checked={choice === value}
                  disabled={writing}
                  onChange={() => setChoice(value)}
                  className="h-4 w-4 accent-primary"
                />
                {label}
              </label>
            ))}
          </div>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
        <p
          className={cn(
            'font-sans text-[13px]',
            short ? 'text-destructive' : 'text-muted-foreground',
          )}
        >
          {plural(count, 'generation')}
          {left !== null && ` · ${left} left`}
          {short && allowance?.mayBuyTopUp && (
            <>
              {' · '}
              <Link to="/settings" className="underline underline-offset-2 hover:text-foreground">
                Top up
              </Link>
            </>
          )}
        </p>
        <Button
          type="button"
          variant="solid"
          className="h-10"
          disabled={!canWrite}
          onClick={() => onWrite(picked, choice)}
        >
          {writing ? 'Starting…' : `Write ${plural(count, 'post')}`}
        </Button>
      </div>
      {children}
      <button
        type="button"
        onClick={onEditBrief}
        disabled={writing}
        className="font-sans text-[13px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline disabled:cursor-not-allowed"
      >
        Edit brief
      </button>
    </section>
  );
}
