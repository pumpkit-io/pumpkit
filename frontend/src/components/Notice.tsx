export function Notice({
  message,
  announced = true,
}: {
  message: string;
  /** False when a live region already mounted elsewhere announces the message. */
  announced?: boolean;
}) {
  return (
    <p
      role={announced ? 'status' : undefined}
      className="rounded-md border border-border bg-muted px-3 py-2 font-sans text-xs text-foreground"
    >
      {message}
    </p>
  );
}
