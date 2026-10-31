import { Check } from 'lucide-react';
import { useInstance } from '@/features/instance/useInstance';
import { cn } from '@/lib/utils';

type StepKey = 'paywall' | 'x_connection' | 'persona';

interface Step {
  key: StepKey;
  label: string;
}

/** The steps before Pumpkit opens, leaving out the Paywall where the Instance sells no Plans. */
function stepsFor(sellsPlans: boolean): Step[] {
  const steps: Step[] = [
    { key: 'paywall', label: 'Plan' },
    { key: 'x_connection', label: 'Connect X' },
    { key: 'persona', label: 'Persona' },
  ];
  return sellsPlans ? steps : steps.filter((step) => step.key !== 'paywall');
}

/** Numbered, since the steps are a sequence: done ones show a check, the current one the accent. */
export function StepIndicator({ current }: { current: StepKey }) {
  const { sells_plans } = useInstance();
  const steps = stepsFor(sells_plans);
  const at = steps.findIndex((step) => step.key === current);

  return (
    <nav aria-label="Steps" className="min-w-0">
      <p className="font-sans text-xs text-muted-foreground sm:hidden">
        Step {at + 1} of {steps.length}
        <span className="text-foreground"> {steps[at]?.label}</span>
      </p>
      <ol className="hidden items-center gap-2 sm:flex">
        {steps.map((step, i) => {
          const done = i < at;
          const isCurrent = i === at;
          return (
            <li key={step.key} className="flex items-center gap-2">
              {i > 0 && <span aria-hidden className="h-px w-6 bg-border" />}
              <span
                aria-current={isCurrent ? 'step' : undefined}
                className={cn(
                  'flex items-center gap-2 font-sans text-sm',
                  isCurrent ? 'font-medium text-foreground' : 'text-muted-foreground',
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs tabular-nums ring-1 ring-inset',
                    isCurrent
                      ? 'bg-primary text-primary-foreground ring-primary'
                      : done
                        ? 'bg-card text-foreground ring-border'
                        : 'text-muted-foreground ring-border',
                  )}
                >
                  {done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </span>
                {step.label}
                {done && <span className="sr-only"> (done)</span>}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
