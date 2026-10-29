import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { CHOOSE_PLAN_PATH, trackChoosePlan } from './choosePlan';

/** Says what needs a Subscription and links to Choose a Plan; `source` tags the analytics. */
export function SubscribePrompt({ message, source }: { message: string; source: string }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="font-sans text-sm text-foreground">{message}</p>
      <Button asChild size="sm" className="h-10 shrink-0">
        <Link to={CHOOSE_PLAN_PATH} onClick={() => trackChoosePlan(source)}>
          Subscribe
        </Link>
      </Button>
    </div>
  );
}
