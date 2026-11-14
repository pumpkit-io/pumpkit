import { storage } from '@/lib/storage';

/**
 * The last draft the Persona step made, so reopening the step shows it instead of spending
 * another of the day's drafts. The Session's end forgets it, as another User may sign in next.
 */
export function keptDraft(): string | null {
  try {
    const value = storage.get<unknown>('positioning-draft', null);
    return typeof value === 'string' ? value : null;
  } catch {
    return null;
  }
}

export function keepDraft(text: string): void {
  try {
    storage.set('positioning-draft', text);
  } catch {
    // Full or blocked storage only means the step drafts again when it reopens.
  }
}

export function forgetDraft(): void {
  try {
    storage.remove('positioning-draft');
  } catch {
    // Blocked storage has kept nothing to forget.
  }
}
