import { Button } from '@/components/ui/button';

export function ErrorBanner({
  message,
  onRetry,
  onDismiss,
}: {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-destructive sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      {(onRetry || onDismiss) && (
        <div className="flex shrink-0 gap-2">
          {onDismiss && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-10 text-destructive"
              onClick={onDismiss}
            >
              Dismiss
            </Button>
          )}
          {onRetry && (
            <Button type="button" size="sm" variant="outline" className="h-10" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
