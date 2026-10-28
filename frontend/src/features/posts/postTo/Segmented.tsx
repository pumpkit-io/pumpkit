import { useId } from 'react';

/** A pair of radio buttons drawn as one segmented control, under a visible legend. */
export function Segmented<T extends string>({
  legend,
  options,
  value,
  onChange,
  disabled,
}: {
  legend: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
}) {
  const name = useId();
  return (
    <fieldset className="space-y-1.5" disabled={disabled}>
      <legend className="font-sans text-sm font-medium text-foreground">{legend}</legend>
      <div className="inline-flex rounded-lg border border-border bg-muted/40 p-1">
        {options.map((option) => (
          <label key={option.value} className="relative">
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
            />
            <span className="block cursor-pointer rounded-md px-4 py-2 font-sans text-sm text-muted-foreground transition-colors peer-checked:bg-card peer-checked:font-medium peer-checked:text-foreground peer-checked:shadow-sm peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-disabled:cursor-not-allowed peer-disabled:opacity-50">
              {option.label}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
