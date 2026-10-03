import React, { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  onError?: (error: Error) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

class TokenErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    // Update state so the next render will show the fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Token error boundary caught an error:', error, errorInfo);

    // If it's a token-related error, handle it appropriately
    if (this.isTokenError(error)) {
      // Clear tokens and redirect to login
      localStorage.removeItem('auth_token');
      localStorage.removeItem('token_expires_at');
      window.location.href = '/login';
      return;
    }

    if (this.props.onError) {
      this.props.onError(error);
    }
  }

  private isTokenError(error: Error): boolean {
    const tokenErrorMessages = [
      'token expired',
      'invalid token',
      'unauthorized',
      'refresh token',
      'authentication failed'
    ];

    const errorMessage = error.message?.toLowerCase() || '';
    return tokenErrorMessages.some(msg => errorMessage.includes(msg));
  }

  render() {
    if (this.state.hasError && this.isTokenError(this.state.error!)) {
      // Don't render anything - user will be redirected
      return null;
    }

    if (this.state.hasError) {
      // Generic error fallback
      return (
        <div className="flex min-h-screen items-center justify-center bg-background">
          <div className="text-center">
            <h2 className="text-2xl font-semibold mb-4">Something went wrong</h2>
            <p className="text-muted-foreground mb-4">
              An unexpected error occurred. Please try refreshing the page.
            </p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90"
            >
              Refresh Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export { TokenErrorBoundary };