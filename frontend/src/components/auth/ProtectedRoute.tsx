import { useEffect, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { returnTo } from '@/lib/returnTo';
import { useAuth } from '../../contexts/AuthContext';

interface ProtectedRouteProps {
  children: ReactNode;
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();
  const signedOut = !isLoading && !isAuthenticated;
  const path = location.pathname + location.search;

  useEffect(() => {
    if (signedOut) returnTo.remember(path);
  }, [signedOut, path]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-foreground">
        <p role="status" className="font-sans text-sm text-muted-foreground">
          Loading…
        </p>
      </div>
    );
  }

  if (signedOut) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
