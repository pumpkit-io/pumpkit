import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useAccount } from './useAccount';
import { useProfile, useProfileMutator } from '@/pages/Home/ProfileContext';
import { userService } from '@/services/userService';
import { AvatarEditor } from './AvatarEditor';
import { track } from '@/lib/analytics';
import { identifyUser } from '@/lib/posthog';
import { APP_NAME } from '@/lib/app';

interface FormState {
  firstName: string;
  lastName: string;
  avatarUrl: string | null;
}

function emptyForm(): FormState {
  return { firstName: '', lastName: '', avatarUrl: null };
}

function formFromProfile(profile: {
  firstName: string | null;
  lastName: string | null;
  avatarUrl: string | null;
}): FormState {
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

export function AccountDialog() {
  const { isOpen, close, error, setError, pendingSave, setPendingSave } = useAccount();
  const profile = useProfile();
  const setProfile = useProfileMutator();

  const [form, setForm] = useState<FormState>(emptyForm);
  const prevOpenRef = useRef(false);

  // Seed the form whenever the dialog flips open so a stale draft doesn't
  // leak between open/close cycles.
  useEffect(() => {
    if (isOpen && profile) {
      setForm(formFromProfile(profile));
      setError(null);
    }
  }, [isOpen, profile, setError]);

  const isDirty = useMemo(() => {
    if (!profile) return false;
    return (
      (form.firstName || null) !== (profile.firstName ?? null) ||
      (form.lastName || null) !== (profile.lastName ?? null) ||
      form.avatarUrl !== profile.avatarUrl
    );
  }, [form, profile]);

  useEffect(() => {
    if (isOpen && !prevOpenRef.current) {
      track('account_dialog_opened');
    } else if (!isOpen && prevOpenRef.current) {
      track('account_dialog_closed', { unsaved_changes: isDirty });
    }
    prevOpenRef.current = isOpen;
  }, [isOpen, isDirty]);

  const heroName = useMemo(() => {
    const composed = `${form.firstName} ${form.lastName}`.trim();
    if (composed) return composed;
    return profile?.email ?? '';
  }, [form, profile]);

  const initials = initialsFor(form.firstName, form.lastName, profile?.email ?? '');

  if (!profile) return null;

  const onSave = async () => {
    setPendingSave(true);
    setError(null);
    const fieldsChanged: string[] = [];
    if ((form.firstName || null) !== (profile?.firstName ?? null)) fieldsChanged.push('first_name');
    if ((form.lastName || null) !== (profile?.lastName ?? null)) fieldsChanged.push('last_name');
    if (form.avatarUrl !== profile?.avatarUrl) fieldsChanged.push('avatar');
    try {
      const next = await userService.updateProfile({
        firstName: form.firstName.trim() || null,
        lastName: form.lastName.trim() || null,
        avatarUrl: form.avatarUrl,
      });
      setProfile(next);
      // Refresh the PostHog person profile so updated name lands server-side
      // without waiting for the next browser session.
      identifyUser(next.id, {
        email: next.email,
        first_name: next.firstName,
        last_name: next.lastName,
      });
      track('account_profile_saved', { fields_changed: fieldsChanged });
      close();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const message =
        typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? String(detail[0]?.msg ?? 'Could not save your changes.')
            : e instanceof Error
              ? e.message
              : 'Could not save your changes.';
      track('account_profile_save_failed', { error_message: message });
      setError(message);
      setPendingSave(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(next) => (next ? null : close())}>
      <DialogContent className="max-w-[560px]">
        <DialogHeader>
          <DialogTitle className="font-sans text-base font-semibold tracking-tight">
            Account
          </DialogTitle>
          <p className="mt-1 font-sans text-xs text-muted-foreground">
            Update how you appear across {APP_NAME}.
          </p>
        </DialogHeader>

        <div className="space-y-5 px-6 pb-4">
          <div className="flex items-center gap-5">
            <AvatarEditor
              value={form.avatarUrl}
              initials={initials}
              onChange={(next) => setForm((f) => ({ ...f, avatarUrl: next }))}
              onError={setError}
            />
            <div className="min-w-0 flex-1">
              <div className="truncate text-2xl leading-tight tracking-tight">
                {heroName || '—'}
              </div>
              <div className="mt-1 truncate font-sans text-sm text-muted-foreground">
                {profile.email}
              </div>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              aria-live="polite"
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-sans text-xs text-destructive"
            >
              {error}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-xs font-medium text-muted-foreground">
                First name
              </span>
              <Input
                value={form.firstName}
                onChange={(e) => setForm((f) => ({ ...f, firstName: e.target.value }))}
                maxLength={80}
                autoComplete="given-name"
                placeholder="First name"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="font-sans text-xs font-medium text-muted-foreground">Last name</span>
              <Input
                value={form.lastName}
                onChange={(e) => setForm((f) => ({ ...f, lastName: e.target.value }))}
                maxLength={80}
                autoComplete="family-name"
                placeholder="Last name"
              />
            </label>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="font-sans text-xs font-medium text-muted-foreground">Email</span>
            <div className="flex items-center gap-3">
              <Input value={profile.email} readOnly disabled className="bg-muted/30" />
              <span className="whitespace-nowrap font-sans text-[11px] text-muted-foreground">
                Managed by sign-in
              </span>
            </div>
          </label>
        </div>

        <DialogFooter>
          <span className="font-sans text-[11px] text-muted-foreground">
            Changes apply everywhere in {APP_NAME}.
          </span>
          <div className="flex items-center gap-2">
            <Button type="button" variant="ghost" onClick={close} disabled={pendingSave}>
              Cancel
            </Button>
            <Button type="button" onClick={onSave} disabled={!isDirty || pendingSave}>
              {pendingSave ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
