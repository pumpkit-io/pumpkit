import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Brand } from '@/components/brand/Brand';
import { CompanyFooter } from '@/features/legal/CompanyFooter';

/** The signed-out shell of the sign-in pages, drawn like FocusedLayout so signing in feels like the app. */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] flex-col bg-background text-foreground">
      <header className="px-4 py-3 sm:px-6">
        <Link
          to="/"
          className="inline-flex rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Brand size="sm" showName />
        </Link>
      </header>
      <main className="flex flex-1 flex-col bg-card px-4 py-10 sm:mx-2 sm:rounded-xl sm:border sm:border-border sm:px-6 sm:py-14 sm:shadow-panel">
        <div className="mx-auto w-full max-w-[380px] sm:my-auto sm:pb-[8vh]">{children}</div>
      </main>
      <CompanyFooter className="border-t-0 py-5" />
    </div>
  );
}

export const AUTH_HEADING_CLASS =
  'font-sans text-2xl/[30px] font-semibold tracking-[-0.015em] text-foreground';
