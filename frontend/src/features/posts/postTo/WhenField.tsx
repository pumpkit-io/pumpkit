import { useId } from 'react';
import { Input } from '@/components/ui/input';
import { localInputValue, TIME_ZONE } from '@/features/scheduledPosts/localTime';
import { Segmented } from './Segmented';

/** Now, or a date and a time as the inputs hold them, in the browser's time zone. */
export interface WhenDraft {
  now: boolean;
  /** 2026-10-12 */
  date: string;
  /** 09:00 */
  time: string;
}

/** Now, with Schedule preset to the next whole hour. */
export function initialWhen(): WhenDraft {
  const next = new Date();
  next.setMinutes(60, 0, 0);
  const [date = '', time = ''] = localInputValue(next).split('T');
  return { now: true, date, time };
}

/** The ISO instant the draft schedules for, or null for Now or a date or time left empty. */
export function publishAtFrom(when: WhenDraft): string | null {
  if (when.now || !when.date || !when.time) return null;
  // A date and time without an offset parse as local time.
  const at = new Date(`${when.date}T${when.time}`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

export function WhenField({
  value,
  onChange,
  disabled,
}: {
  value: WhenDraft;
  onChange: (value: WhenDraft) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const today = localInputValue(new Date()).split('T')[0];
  return (
    <div className="space-y-3">
      <Segmented
        legend="When"
        options={[
          { value: 'now', label: 'Now' },
          { value: 'schedule', label: 'Schedule' },
        ]}
        value={value.now ? 'now' : 'schedule'}
        onChange={(next) => onChange({ ...value, now: next === 'now' })}
        disabled={disabled}
      />
      {!value.now && (
        <div className="space-y-1.5">
          <div className="grid grid-cols-2 gap-3 sm:w-80">
            <div className="space-y-1.5">
              <label
                htmlFor={`${id}-date`}
                className="block font-sans text-sm font-medium text-foreground"
              >
                Date
              </label>
              <Input
                id={`${id}-date`}
                type="date"
                value={value.date}
                min={today}
                onChange={(e) => onChange({ ...value, date: e.target.value })}
                disabled={disabled}
              />
            </div>
            <div className="space-y-1.5">
              <label
                htmlFor={`${id}-time`}
                className="block font-sans text-sm font-medium text-foreground"
              >
                Time
              </label>
              <Input
                id={`${id}-time`}
                type="time"
                value={value.time}
                onChange={(e) => onChange({ ...value, time: e.target.value })}
                disabled={disabled}
              />
            </div>
          </div>
          <p className="font-sans text-xs text-muted-foreground">In your time zone, {TIME_ZONE}.</p>
        </div>
      )}
    </div>
  );
}
