import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

export function EmailConfirmationRedirect() {
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const token = searchParams.get('token');

    if (token) {
      const backendConfirmUrl = `${import.meta.env.VITE_API_URL}/confirm-email?token=${encodeURIComponent(token)}`;
      window.location.href = backendConfirmUrl;
    } else {
      window.location.href = '/login?error=invalid_confirmation_link';
    }
  }, [searchParams]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="text-center">
        <p className="text-sm text-muted-foreground">
          Confirming your email...
        </p>
      </div>
    </div>
  );
}
