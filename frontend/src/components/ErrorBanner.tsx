import { Button } from '@/components/ui/button';

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-red-700 dark:text-red-300 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      {onRetry && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-10 shrink-0"
          onClick={onRetry}
        >
          Try again
        </Button>
      )}
    </div>
  );
}
