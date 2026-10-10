import { useId } from 'react';
import { Input } from '@/components/ui/input';
import { earliestInputValue, TIME_ZONE } from './localTime';

/** A date and time in the browser's timezone, as a datetime-local value; '' when none. */
export function PublishTimeField({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block font-sans text-sm font-medium text-foreground">
        Date and time
      </label>
      <Input
        id={id}
        type="datetime-local"
        value={value}
        min={earliestInputValue()}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="sm:w-64"
      />
      <p className="font-sans text-xs text-muted-foreground">
        Times are in your timezone, {TIME_ZONE}.
      </p>
    </div>
  );
}
