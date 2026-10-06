export function LimitNotice({ message }: { message: string }) {
  return (
    <p
      role="status"
      className="rounded-md border border-border bg-muted px-3 py-2 font-sans text-xs text-foreground"
    >
      {message}
    </p>
  );
}
