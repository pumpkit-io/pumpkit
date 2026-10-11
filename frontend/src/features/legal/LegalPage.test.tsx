import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { legalRoutes } from './legalRoutes';

/** Renders a legal route as a signed-out visitor opening it directly. */
function renderLegalRoute(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>{legalRoutes}</Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

afterEach(() => {
  document.title = '';
  document.documentElement.removeAttribute('lang');
});

describe('Privacy Policy at /privacy', () => {
  it('renders its heading and Last updated date for a signed-out visitor', () => {
    renderLegalRoute('/privacy');
    const main = screen.getByRole('main');
    expect(within(main).getByRole('heading', { level: 1 })).toHaveTextContent('Privacy Policy');
    expect(within(main).getByText('Last updated: 11 October 2026')).toBeInTheDocument();
  });

  it('sets its own page title and English as the page language', () => {
    renderLegalRoute('/privacy');
    expect(document.title).toBe('Privacy Policy · Pumpkit');
    expect(document.documentElement.lang).toBe('en');
  });

  it('gives its sections headings that can be linked to', () => {
    renderLegalRoute('/privacy');
    const cookies = screen.getByRole('heading', { level: 2, name: 'Cookies and browser storage' });
    expect(cookies).toHaveAttribute('id', 'cookies');
    expect(screen.getByRole('heading', { level: 2, name: 'Inspiration authors' })).toHaveAttribute(
      'id',
      'inspiration-authors',
    );
  });

  it('names the Operator and the support address', () => {
    renderLegalRoute('/privacy');
    const main = screen.getByRole('main');
    expect(within(main).getAllByText(/INCEPTIONAL S\.R\.L\./).length).toBeGreaterThan(0);
    expect(within(main).getAllByRole('link', { name: 'support@pumpkit.io' })[0]).toHaveAttribute(
      'href',
      'mailto:support@pumpkit.io',
    );
  });

  it('ends with the company footer', () => {
    renderLegalRoute('/privacy');
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText(/INCEPTIONAL S\.R\.L\./)).toBeInTheDocument();
  });
});
