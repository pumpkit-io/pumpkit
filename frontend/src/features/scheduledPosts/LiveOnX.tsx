/** Marks Part `number` as live, linking to it on X when the link is known. */
export function LiveOnX({ number, xPostUrl }: { number: number; xPostUrl: string | null }) {
  const label = `Part ${number} is live on X`;
  const className = 'font-sans text-xs font-medium text-green-700 dark:text-green-300';
  if (!xPostUrl) {
    return (
      <span className={className} aria-label={label}>
        Live on X
      </span>
    );
  }
  return (
    <a
      href={xPostUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={label}
      className={`${className} underline underline-offset-2`}
    >
      Live on X
    </a>
  );
}
