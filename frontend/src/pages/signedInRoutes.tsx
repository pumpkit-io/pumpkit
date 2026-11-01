import { Navigate, Outlet, Route } from 'react-router-dom';
import { OnboardingGate } from '@/features/onboarding/OnboardingGate';
import { APP_HOME, ONBOARDING_PATH, PAYWALL_PATH } from '@/features/onboarding/paths';
import { STATUS_TAB, TAB_ORDER } from '@/features/posts/postStatus';
import { AppLayout } from './AppLayout';
import { FocusedLayout } from './FocusedLayout';
import { NewPost } from './NewPost';
import { OAuthConsent, OAUTH_CONSENT_PATH } from './OAuthConsent';
import { Onboarding } from './Onboarding';
import { OnboardingLayout } from './OnboardingLayout';
import { Paywall } from './Paywall';
import { Persona } from './Persona';
import { PostPage } from './PostPage';
import { Posts } from './Posts';
import { Settings } from './Settings';

/**
 * Every signed-in page, for App and for the page tests, which render the same tree. Each layout
 * sits behind a gate that sends the User to the page their next step is on (ADR 0018), except
 * the consent page's (ADR 0020).
 */
export function signedInRoutes() {
  return (
    <>
      <Route
        element={
          <OnboardingGate home={APP_HOME}>
            <AppLayout />
          </OnboardingGate>
        }
      >
        <Route path="/new" element={<NewPost />} />
        <Route path="/posts" element={<Navigate to={STATUS_TAB.scheduled.path} replace />} />
        {TAB_ORDER.map((status) => (
          <Route key={status} path={STATUS_TAB[status].path} element={<Posts status={status} />} />
        ))}
        <Route path="/posts/:id" element={<PostPage />} />
        <Route path="/persona" element={<Persona />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/home" element={<Navigate to="/new" replace />} />
        <Route path="/scheduled" element={<Navigate to={STATUS_TAB.scheduled.path} replace />} />
      </Route>
      <Route
        element={
          <OnboardingGate home={PAYWALL_PATH}>
            <OnboardingLayout />
          </OnboardingGate>
        }
      >
        <Route path={PAYWALL_PATH} element={<Paywall />} />
      </Route>
      <Route
        element={
          <OnboardingGate home={ONBOARDING_PATH}>
            <OnboardingLayout />
          </OnboardingGate>
        }
      >
        <Route path={ONBOARDING_PATH} element={<Onboarding />} />
      </Route>
      {/* No gate: a User mid-Onboarding or without a Subscription can still connect an app. */}
      <Route
        element={
          <FocusedLayout>
            <Outlet />
          </FocusedLayout>
        }
      >
        <Route path={OAUTH_CONSENT_PATH} element={<OAuthConsent />} />
      </Route>
    </>
  );
}
