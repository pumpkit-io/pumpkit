import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('posthog-js', () => {
  const posthog = {
    __loaded: false,
    init: vi.fn(() => {
      posthog.__loaded = true;
    }),
    opt_in_capturing: vi.fn(),
    opt_out_capturing: vi.fn(),
    reset: vi.fn(),
    identify: vi.fn(),
    capture: vi.fn(),
    register: vi.fn(),
  };
  return { default: posthog };
});

import posthog from 'posthog-js';
import { CompanyFooter } from '@/features/legal/CompanyFooter';
import { PostHogPageviewTracker } from '@/lib/PostHogPageviewTracker';
import { track } from '@/lib/analytics';
import { startAnalytics } from '@/lib/analyticsConsent';
import { ConsentBanner } from './ConsentBanner';

const mocked = posthog as unknown as typeof posthog & { __loaded: boolean };

/** A visitor on a public page: the banner, the pageview tracker and the company footer. */
function renderPage(path = '/login') {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <PostHogPageviewTracker />
      <ConsentBanner />
      <CompanyFooter />
    </MemoryRouter>,
  );
}

const banner = () => screen.queryByRole('region', { name: 'Analytics consent' });
const choose = (name: 'Accept' | 'Reject') =>
  fireEvent.click(within(banner()!).getByRole('button', { name }));

function clearCookies() {
  for (const cookie of document.cookie.split(';')) {
    const name = cookie.split('=')[0].trim();
    if (name) document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  }
}

beforeEach(() => {
  vi.stubEnv('VITE_POSTHOG_ENABLED', 'true');
  vi.stubEnv('VITE_POSTHOG_KEY', 'phc_test');
  localStorage.clear();
  sessionStorage.clear();
  clearCookies();
  mocked.__loaded = false;
  vi.clearAllMocks();
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe('Analytics consent with no stored choice', () => {
  it('shows the banner, linking to the cookie section, and never starts PostHog', () => {
    startAnalytics();
    renderPage();
    expect(banner()).toBeInTheDocument();
    expect(within(banner()!).getByRole('link', { name: /cookies/i })).toHaveAttribute(
      'href',
      '/privacy#cookies',
    );
    track('login_google_clicked');
    expect(posthog.init).not.toHaveBeenCalled();
    expect(posthog.capture).not.toHaveBeenCalled();
  });

  it('gives Accept and Reject the same size and visual weight', () => {
    renderPage();
    const accept = within(banner()!).getByRole('button', { name: 'Accept' });
    const reject = within(banner()!).getByRole('button', { name: 'Reject' });
    expect(accept.className).toBe(reject.className);
  });
});

describe('Rejecting analytics', () => {
  it('stores denied, hides the banner and never starts PostHog', () => {
    renderPage();
    choose('Reject');
    expect(localStorage.getItem('pumpkit:analytics-consent')).toBe('"denied"');
    expect(banner()).not.toBeInTheDocument();
    track('login_google_clicked');
    expect(posthog.init).not.toHaveBeenCalled();
    expect(posthog.capture).not.toHaveBeenCalled();
  });

  it('keeps the banner hidden on the next visit without starting PostHog', () => {
    localStorage.setItem('pumpkit:analytics-consent', '"denied"');
    startAnalytics();
    renderPage();
    expect(banner()).not.toBeInTheDocument();
    expect(posthog.init).not.toHaveBeenCalled();
  });
});

describe('Accepting analytics', () => {
  it('stores granted, hides the banner and starts PostHog on this page view', () => {
    renderPage('/login');
    choose('Accept');
    expect(localStorage.getItem('pumpkit:analytics-consent')).toBe('"granted"');
    expect(banner()).not.toBeInTheDocument();
    expect(posthog.init).toHaveBeenCalledTimes(1);
    expect(posthog.opt_in_capturing).toHaveBeenCalled();
    expect(posthog.capture).toHaveBeenCalledWith('$pageview', {
      $current_url: `${window.location.origin}/login`,
    });
  });

  it('lets declared events through once accepted', () => {
    renderPage();
    choose('Accept');
    track('login_google_clicked');
    expect(posthog.capture).toHaveBeenCalledWith('login_google_clicked', undefined);
  });

  it('starts PostHog at app start on the next visit and keeps the banner hidden', () => {
    localStorage.setItem('pumpkit:analytics-consent', '"granted"');
    startAnalytics();
    renderPage();
    expect(posthog.init).toHaveBeenCalledTimes(1);
    expect(banner()).not.toBeInTheDocument();
  });
});

describe('Cookie settings', () => {
  it('reopens the banner from the footer', () => {
    localStorage.setItem('pumpkit:analytics-consent', '"denied"');
    renderPage();
    expect(banner()).not.toBeInTheDocument();
    fireEvent.click(
      within(screen.getByRole('contentinfo')).getByRole('button', { name: 'Cookie settings' }),
    );
    expect(banner()).toBeInTheDocument();
    expect(banner()).toHaveFocus();
  });

  it('withdraws consent: opts PostHog out, resets it and clears what it stored', () => {
    renderPage();
    choose('Accept');
    localStorage.setItem('ph_phc_test_posthog', '{"distinct_id":"x"}');
    localStorage.setItem('__ph_opt_in_out_phc_test', '1');
    sessionStorage.setItem('ph_phc_test_window_id', 'w');
    sessionStorage.setItem('pumpkit:posthog-identified', '1');
    document.cookie = 'ph_phc_test_posthog=x; path=/';
    localStorage.setItem('pumpkit:theme', '"dark"');

    fireEvent.click(screen.getByRole('button', { name: 'Cookie settings' }));
    choose('Reject');

    expect(localStorage.getItem('pumpkit:analytics-consent')).toBe('"denied"');
    expect(posthog.opt_out_capturing).toHaveBeenCalled();
    expect(posthog.reset).toHaveBeenCalled();
    expect(localStorage.getItem('ph_phc_test_posthog')).toBeNull();
    expect(localStorage.getItem('__ph_opt_in_out_phc_test')).toBeNull();
    expect(sessionStorage.getItem('ph_phc_test_window_id')).toBeNull();
    expect(sessionStorage.getItem('pumpkit:posthog-identified')).toBeNull();
    expect(document.cookie).not.toContain('ph_phc_test_posthog');
    expect(localStorage.getItem('pumpkit:theme')).toBe('"dark"');

    vi.mocked(posthog.capture).mockClear();
    track('login_google_clicked');
    expect(posthog.capture).not.toHaveBeenCalled();
  });

  it('gives consent again after a withdrawal without a reload', () => {
    renderPage();
    choose('Accept');
    fireEvent.click(screen.getByRole('button', { name: 'Cookie settings' }));
    choose('Reject');
    fireEvent.click(screen.getByRole('button', { name: 'Cookie settings' }));
    act(() => choose('Accept'));
    expect(posthog.init).toHaveBeenCalledTimes(1);
    expect(posthog.opt_in_capturing).toHaveBeenCalledTimes(2);
    track('login_google_clicked');
    expect(posthog.capture).toHaveBeenCalledWith('login_google_clicked', undefined);
  });
});
