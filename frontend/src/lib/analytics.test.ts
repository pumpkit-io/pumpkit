import { describe, expect, it, vi } from 'vitest';

vi.mock('./posthog', () => ({ posthog: { capture: vi.fn(), register: vi.fn() } }));

import { posthog } from './posthog';
import { EVENTS, registerSuperProperties, track } from './analytics';

describe('analytics (disabled by default)', () => {
  it('does not call PostHog when disabled', () => {
    track('login_google_clicked');
    registerSuperProperties({ theme: 'light' });
    expect(posthog.capture).not.toHaveBeenCalled();
    expect(posthog.register).not.toHaveBeenCalled();
  });

  it('documents every event', () => {
    for (const [name, def] of Object.entries(EVENTS)) {
      expect(def.description.length, name).toBeGreaterThan(10);
    }
  });
});
