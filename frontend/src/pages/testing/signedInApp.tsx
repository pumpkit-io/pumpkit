import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider } from '@/contexts/AuthContext';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { OnboardingProvider } from '@/features/onboarding/OnboardingProvider';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import type { Instance } from '@/lib/instance';
import type { BillingMe } from '@/services/billingService';
import type { NextStep } from '@/services/onboardingService';
import type { InspirationAuthor } from '@/services/inspirationAuthorService';
import type { PostsPage } from '@/services/postService';
import { SignedInHome } from '../SignedInHome';
import { signedInRoutes } from '../signedInRoutes';

/**
 * For tests: the signed-in route tree at `path`, as App mounts it behind sign-in. The User starts
 * at `nextStep`, past the Paywall by default; later checks go to the mocked onboardingService.
 */
export function renderSignedIn(
  path: string,
  {
    state,
    instance = SELLS_PLANS,
    nextStep = null,
  }: { state?: unknown; instance?: Instance; nextStep?: NextStep | null } = {},
) {
  return render(
    <InstanceProvider instance={instance}>
      <AuthProvider>
        <OnboardingProvider initialNextStep={nextStep}>
          <ThemeProvider>
            <MemoryRouter
              initialEntries={[{ pathname: path, state }]}
              future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
            >
              <Routes>
                <Route path="/" element={<SignedInHome />} />
                {signedInRoutes()}
              </Routes>
              <CurrentPath />
            </MemoryRouter>
          </ThemeProvider>
        </OnboardingProvider>
      </AuthProvider>
    </InstanceProvider>,
  );
}

/** Where the router is now, as `CurrentPath` shows it. */
export function currentPath(): string | null {
  return screen.getByRole('status', { name: 'Current path' }).textContent;
}

/** Shows the router's path and state so a test can read where a click or a redirect landed. */
function CurrentPath() {
  const { pathname, state } = useLocation();
  return (
    <>
      <output aria-label="Current path">{pathname}</output>
      <output aria-label="Current state">{JSON.stringify(state ?? null)}</output>
    </>
  );
}

export const NOT_SUBSCRIBED: BillingMe = {
  subscription: null,
  subscribed: false,
  maySubscribe: true,
  trialDays: null,
};

export const SUBSCRIBED: BillingMe = {
  subscription: {
    status: 'active',
    planKey: 'pumpkit_pro_monthly',
    currentPeriodEnd: null,
    cancelAtPeriodEnd: false,
  },
  subscribed: true,
  maySubscribe: false,
  trialDays: null,
};

export const LEVELSIO: InspirationAuthor = {
  handle: 'levelsio',
  lastFetchedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  postCount: 18,
  photoUrl: null,
};

export const PAULG: InspirationAuthor = {
  handle: 'paulg',
  lastFetchedAt: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  postCount: 20,
  photoUrl: null,
};

export const NAVAL: InspirationAuthor = {
  handle: 'naval',
  lastFetchedAt: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
  postCount: 20,
  photoUrl: null,
};

/** An axios-shaped rejection carrying the backend's status and `detail`. */
export function apiError(status: number, detail: string, extra: Record<string, unknown> = {}) {
  return Object.assign(new Error(`Request failed with status code ${status}`), {
    isAxiosError: true,
    response: { status, data: { detail, ...extra } },
  });
}

/** `postService.list`'s answer for a User with no Posts. */
export const NO_POSTS: PostsPage = {
  posts: [],
  counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
  nextOffset: null,
};
