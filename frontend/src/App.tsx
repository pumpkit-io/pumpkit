import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AppLayout } from './pages/AppLayout';
import { Home } from './pages/Home';
import { Scheduled } from './pages/Scheduled';
import { XConnectionCallback } from './pages/XConnectionCallback';
import { Login } from './pages/Login';
import { Landing } from './pages/Landing';
import { GoogleAuthCallback } from './components/google/GoogleAuthCallback';
import { MagicLinkCallback } from './pages/MagicLinkCallback';
import { MagicLinkSent } from './pages/MagicLinkSent';
import { BillingCancelledRedirect, BillingSuccessRedirect } from './pages/BillingRedirect';
import { AuthProvider, BYPASS_AUTH, useAuth } from './contexts/AuthContext';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { ThemeProvider } from './features/theme/ThemeProvider';
import { PostHogPageviewTracker } from './lib/PostHogPageviewTracker';
import { RobotsMetaController } from './lib/RobotsMetaController';

function FullPageLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
      <p role="status" className="font-sans text-sm text-muted-foreground">
        Loading…
      </p>
    </div>
  );
}

function RootRedirect() {
  const { isAuthenticated, isLoading } = useAuth();
  if (isLoading) return <FullPageLoading />;
  if (BYPASS_AUTH) return <Landing />;
  return isAuthenticated ? <Navigate to="/home" replace /> : <Landing />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/home" element={<Home />} />
        <Route path="/scheduled" element={<Scheduled />} />
      </Route>
      <Route
        path="/oauth/x/callback"
        element={
          <ProtectedRoute>
            <XConnectionCallback />
          </ProtectedRoute>
        }
      />
      <Route path="/oauth/google/callback" element={<GoogleAuthCallback />} />
      <Route path="/auth/magic-link/callback" element={<MagicLinkCallback />} />
      <Route path="/login/magic-link/sent" element={<MagicLinkSent />} />
      <Route
        path="/billing/success"
        element={
          <ProtectedRoute>
            <BillingSuccessRedirect />
          </ProtectedRoute>
        }
      />
      <Route
        path="/billing/cancelled"
        element={
          <ProtectedRoute>
            <BillingCancelledRedirect />
          </ProtectedRoute>
        }
      />
      <Route
        path="/billing"
        element={
          <ProtectedRoute>
            <Navigate to="/home" replace state={{ openBilling: true }} />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <ThemeProvider>
        <Router>
          <PostHogPageviewTracker />
          <RobotsMetaController />
          <AppRoutes />
        </Router>
      </ThemeProvider>
    </AuthProvider>
  );
}

export default App;
