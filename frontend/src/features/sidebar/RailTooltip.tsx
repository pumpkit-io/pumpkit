/** Hover label for an icon-only sidebar button; the button needs `group relative`. */
export function RailTooltip({ label }: { label: string }) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute left-full z-10 ml-3 -translate-x-2 whitespace-nowrap rounded-lg bg-popover px-3 py-1 text-xs font-medium text-popover-foreground opacity-0 shadow-lg transition-all duration-150 ease-out group-hover:translate-x-0 group-hover:opacity-100"
    >
      {label}
    </span>
  );
}
