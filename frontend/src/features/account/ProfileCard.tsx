import { useEffect, useMemo, useState } from 'react';
import { ErrorBanner } from '@/components/ErrorBanner';
import { SettingsCard } from '@/components/SettingsCard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useInstance } from '@/features/instance/useInstance';
import { useXConnectionContext } from '@/features/xConnection/useXConnectionContext';
import { track } from '@/lib/analytics';
import { identifyUser } from '@/lib/analyticsConsent';
import { useProfile, useProfileMutator } from '@/pages/layout/ProfileContext';
import { errorMessage } from '@/services/apiErrors';
import { userService, type UserProfile } from '@/services/userService';
import { AvatarEditor } from './AvatarEditor';

interface FormState {
  firstName: string;
  lastName: string;
  avatarUrl: string | null;
}

function formFromProfile(profile: UserProfile): FormState {
  return {
    firstName: profile.firstName ?? '',
    lastName: profile.lastName ?? '',
    avatarUrl: profile.avatarUrl,
  };
}

function initialsFor(firstName: string, lastName: string, fallback: string): string {
  const first = firstName.trim()[0] ?? '';
  const last = lastName.trim()[0] ?? '';
  const combined = (first + last).toUpperCase();
  if (combined) return combined;
  return (fallback.trim()[0] ?? '•').toUpperCase();
}

/** The fields that differ from the stored profile, named as analytics reports them. */
function changedFields(form: FormState, profile: UserProfile): string[] {
  const changed: string[] = [];
  if ((form.firstName.trim() || null) !== (profile.firstName ?? null)) changed.push('first_name');
  if ((form.lastName.trim() || null) !== (profile.lastName ?? null)) changed.push('last_name');
  if (form.avatarUrl !== profile.avatarUrl) changed.push('avatar');
  return changed;
}

/** The backend's sentence, including the first of a validation error's messages. */
function saveError(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg;
  return errorMessage(e, "Couldn't save your changes. Try again.");
}

const X_PHOTO_FAILED = "Couldn't use your X photo. Try again.";

const LABEL = 'font-sans text-xs font-medium text-muted-foreground';

/** The photo and names Parts are shown with, and the sign-in email, which only sign-in changes. */
export function ProfileCard() {
  const { app_name } = useInstance();
  const profile = useProfile();
  const setProfile = useProfileMutator();
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { connection, acceptPhoto } = useXConnectionContext();
  const [usingXPhoto, setUsingXPhoto] = useState(false);

  // Reseed from every new profile, the one a save answers with included.
  useEffect(() => {
    if (profile) setForm(formFromProfile(profile));
  }, [profile]);

  const changed = useMemo(
    () => (profile && form ? changedFields(form, profile) : []),
    [form, profile],
  );

  const edit = (next: Partial<FormState>) => {
    setSaved(false);
    setForm((current) => (current ? { ...current, ...next } : current));
  };

  const save = async () => {
    if (!form) return;
    setSaving(true);
    setError(null);
    try {
      const next = await userService.updateProfile({
        firstName: form.firstName.trim() || null,
        lastName: form.lastName.trim() || null,
        avatarUrl: form.avatarUrl,
      });
      setProfile(next);
      // Update the PostHog person now rather than at the next browser session.
      identifyUser(next.id, {
        email: next.email,
        first_name: next.firstName,
        last_name: next.lastName,
      });
      track('account_profile_saved', { fields_changed: changed });
      setSaved(true);
    } catch (e) {
      const message = saveError(e);
      track('account_profile_save_failed', { error_message: message });
      setError(message);
    } finally {
      setSaving(false);
    }
  };

  const takeXPhoto = async () => {
    setUsingXPhoto(true);
    setError(null);
    try {
      setProfile(await acceptPhoto());
      track('account_x_photo_used');
    } catch {
      setError(X_PHOTO_FAILED);
    } finally {
      setUsingXPhoto(false);
    }
  };

  return (
    <SettingsCard title="Profile" description={`How you appear across ${app_name}.`}>
      {!profile || !form ? (
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading your profile…
        </p>
      ) : (
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
            <AvatarEditor
              value={form.avatarUrl}
              initials={initialsFor(form.firstName, form.lastName, profile.email)}
              onChange={(avatarUrl) => edit({ avatarUrl })}
              onError={setError}
              onUseXPhoto={connection?.photoUrl ? () => void takeXPhoto() : undefined}
              usingXPhoto={usingXPhoto}
            />
            <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1.5">
                <span className={LABEL}>First name</span>
                <Input
                  value={form.firstName}
                  onChange={(e) => edit({ firstName: e.target.value })}
                  maxLength={80}
                  autoComplete="given-name"
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className={LABEL}>Last name</span>
                <Input
                  value={form.lastName}
                  onChange={(e) => edit({ lastName: e.target.value })}
                  maxLength={80}
                  autoComplete="family-name"
                />
              </label>
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <label htmlFor="profile-email" className={LABEL}>
                  Email
                </label>
                <Input
                  id="profile-email"
                  value={profile.email}
                  readOnly
                  aria-describedby="profile-email-note"
                  className="bg-muted/30 text-muted-foreground"
                />
                <p id="profile-email-note" className="font-sans text-xs text-muted-foreground">
                  Managed by sign-in
                </p>
              </div>
            </div>
          </div>

          {error && <ErrorBanner message={error} />}

          <div className="flex items-center justify-end gap-3">
            {saved && (
              <p role="status" className="font-sans text-xs text-success">
                Saved.
              </p>
            )}
            <Button type="submit" className="h-10" disabled={changed.length === 0 || saving}>
              {saving ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </form>
      )}
    </SettingsCard>
  );
}
