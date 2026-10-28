import { useId } from 'react';
import { Input } from '@/components/ui/input';
import { localInputValue, TIME_ZONE } from '@/features/scheduledPosts/localTime';
import { Segmented } from './Segmented';

/** A date and a time as the inputs hold them, in the browser's time zone. */
export interface DateTimeDraft {
  /** 2026-10-12 */
  date: string;
  /** 09:00 */
  time: string;
}

/** Now, or a date and a time. */
export interface WhenDraft extends DateTimeDraft {
  now: boolean;
}

/** `iso` as the date and time inputs hold it. */
export function dateTimeOf(iso: string): DateTimeDraft {
  const [date = '', time = ''] = localInputValue(new Date(iso)).split('T');
  return { date, time };
}

/** Now, with Schedule preset to the next whole hour. */
export function initialWhen(): WhenDraft {
  const next = new Date();
  next.setMinutes(60, 0, 0);
  return { now: true, ...dateTimeOf(next.toISOString()) };
}

/** The ISO instant of a date and time, or null while either is empty. */
export function instantOf({ date, time }: DateTimeDraft): string | null {
  if (!date || !time) return null;
  // A date and time without an offset parse as local time.
  const at = new Date(`${date}T${time}`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

/** The ISO instant the draft schedules for, or null for Now or a date or time left empty. */
export function publishAtFrom(when: WhenDraft): string | null {
  return when.now ? null : instantOf(when);
}

/** The Date and Time inputs, with the time zone they are in. */
export function DateTimeFields({
  value,
  onChange,
  disabled,
}: {
  value: DateTimeDraft;
  onChange: (value: DateTimeDraft) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const today = localInputValue(new Date()).split('T')[0];
  return (
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
  );
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
        <DateTimeFields
          value={value}
          onChange={(next) => onChange({ ...value, ...next })}
          disabled={disabled}
        />
      )}
    </div>
  );
}
