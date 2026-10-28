import { SettingsCard } from '@/components/SettingsCard';
import { track } from '@/lib/analytics';
import { cn } from '@/lib/utils';
import { useTheme, type ThemeChoice } from './useTheme';

const CHOICES: { value: ThemeChoice; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

/** Light, Dark, or whatever the device prefers. */
export function AppearanceCard() {
  const { choice, setChoice } = useTheme();

  return (
    <SettingsCard title="Appearance" description="System follows your device's setting.">
      <fieldset className="inline-flex rounded-lg border border-border bg-background p-1">
        <legend className="sr-only">Theme</legend>
        {CHOICES.map(({ value, label }) => (
          <label
            key={value}
            className={cn(
              'relative cursor-pointer rounded-md px-4 py-2 font-sans text-sm text-muted-foreground transition-colors',
              'hover:text-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
              choice === value && 'bg-[var(--hover)] font-medium text-foreground',
            )}
          >
            <input
              type="radio"
              name="theme"
              value={value}
              checked={choice === value}
              onChange={() => {
                track('settings_theme_changed', { theme: value });
                setChoice(value);
              }}
              className="sr-only"
            />
            {label}
          </label>
        ))}
      </fieldset>
    </SettingsCard>
  );
}
