import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { InstanceProvider } from '@/features/instance/InstanceProvider';
import { WITH_OPERATOR } from '@/features/instance/testInstances';
import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { DEFAULT_INSTANCE, type Instance } from '@/lib/instance';
import { legalRoutes } from './legalRoutes';

/** Renders a legal route as a signed-out visitor opening it directly. */
function renderLegalRoute(path: string, instance: Instance = WITH_OPERATOR) {
  return render(
    <InstanceProvider instance={instance}>
      <ThemeProvider>
        <MemoryRouter
          initialEntries={[path]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <Routes>{legalRoutes(instance.operator)}</Routes>
        </MemoryRouter>
      </ThemeProvider>
    </InstanceProvider>,
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
    expect(within(main).getByText('Last updated: 30 October 2026')).toBeInTheDocument();
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
    expect(within(footer).getByText(/Example S\.R\.L\./)).toBeInTheDocument();
  });
});

describe('Terms at /terms', () => {
  it('renders its heading and Last updated date for a signed-out visitor', () => {
    renderLegalRoute('/terms');
    const main = screen.getByRole('main');
    expect(within(main).getByRole('heading', { level: 1 })).toHaveTextContent('Terms');
    expect(within(main).getByText('Last updated: 1 November 2026')).toBeInTheDocument();
  });

  it.each([
    ['9. Suspension and termination by the Operator', 'suspension'],
    ['12. Automatic renewal and cancellation', 'renewal'],
    ['14. No refunds', 'refunds'],
    ['16. Limitation of liability', 'liability'],
    ['19. Changes to these Terms', 'changes'],
    ['21. Competent court', 'courts'],
  ])('gives the onerous clause "%s" the anchor #%s', (name, id) => {
    renderLegalRoute('/terms');
    expect(screen.getByRole('heading', { level: 2, name })).toHaveAttribute('id', id);
  });

  it('gives Top-ups their own clause, #top-ups', () => {
    renderLegalRoute('/terms');
    const heading = screen.getByRole('heading', { level: 2, name: '11. Allowance and Top-ups' });
    expect(heading).toHaveAttribute('id', 'top-ups');
  });
});

describe('Informativa sulla privacy at /it/privacy', () => {
  it('renders its Italian heading and the same Last updated date for a signed-out visitor', () => {
    renderLegalRoute('/it/privacy');
    const main = screen.getByRole('main');
    expect(within(main).getByRole('heading', { level: 1 })).toHaveTextContent(
      'Informativa sulla privacy',
    );
    expect(within(main).getByText('Ultimo aggiornamento: 30 ottobre 2026')).toBeInTheDocument();
  });

  it('sets its own page title and Italian as the page language', () => {
    renderLegalRoute('/it/privacy');
    expect(document.title).toBe('Informativa sulla privacy · Pumpkit');
    expect(document.documentElement.lang).toBe('it');
  });

  it('keeps the English anchors on its sections', () => {
    renderLegalRoute('/it/privacy');
    expect(
      screen.getByRole('heading', { level: 2, name: 'Cookie e archiviazione nel browser' }),
    ).toHaveAttribute('id', 'cookies');
    expect(screen.getByRole('heading', { level: 2, name: 'Inspiration author' })).toHaveAttribute(
      'id',
      'inspiration-authors',
    );
  });
});

describe('Termini at /it/terms', () => {
  it('renders its Italian heading and the same Last updated date for a signed-out visitor', () => {
    renderLegalRoute('/it/terms');
    const main = screen.getByRole('main');
    expect(within(main).getByRole('heading', { level: 1 })).toHaveTextContent('Termini');
    expect(within(main).getByText('Ultimo aggiornamento: 1 novembre 2026')).toBeInTheDocument();
  });

  it('sets Italian as the page language', () => {
    renderLegalRoute('/it/terms');
    expect(document.documentElement.lang).toBe('it');
  });

  it.each([
    ['9. Sospensione e risoluzione da parte del Gestore', 'suspension'],
    ['11. Allowance e Top-up', 'top-ups'],
    ['12. Rinnovo automatico e disdetta', 'renewal'],
    ['13. Diritto di recesso per i consumatori', 'withdrawal'],
    ['14. Esclusione dei rimborsi', 'refunds'],
    ['16. Limitazione di responsabilità', 'liability'],
    ['19. Modifiche ai presenti Termini', 'changes'],
    ['21. Foro competente', 'courts'],
  ])('gives clause "%s" the same anchor as the English Terms, #%s', (name, id) => {
    renderLegalRoute('/it/terms');
    expect(screen.getByRole('heading', { level: 2, name })).toHaveAttribute('id', id);
  });

  it('numbers the same clauses as the English Terms, with the same anchors', () => {
    const clauses = (path: string) => {
      const { unmount } = renderLegalRoute(path);
      const found = screen
        .getAllByRole('heading', { level: 2 })
        .map((heading) => `${heading.textContent?.match(/^(\d+)\./)?.[1] ?? '-'} #${heading.id}`);
      unmount();
      return found;
    };
    const english = clauses('/terms');
    expect(english).toHaveLength(23);
    expect(clauses('/it/terms')).toEqual(english);
  });
});

describe('language links', () => {
  it.each([
    ['/privacy', 'Leggi in italiano', '/it/privacy', 'Informativa sulla privacy'],
    ['/it/privacy', 'Read in English', '/privacy', 'Privacy Policy'],
    ['/terms', 'Leggi in italiano', '/it/terms', 'Termini'],
    ['/it/terms', 'Read in English', '/terms', 'Terms'],
  ])('%s offers "%s", which opens %s', (from, label, to, title) => {
    renderLegalRoute(from);
    const link = screen.getByRole('link', { name: label });
    expect(link).toHaveAttribute('href', to);
    fireEvent.click(link);
    expect(within(screen.getByRole('main')).getByRole('heading', { level: 1 })).toHaveTextContent(
      title,
    );
  });
});

describe('every legal document', () => {
  it.each(['/privacy', '/terms', '/it/privacy', '/it/terms'])(
    '%s gives every section heading an explicit {#anchor} id',
    (path) => {
      renderLegalRoute(path);
      const main = screen.getByRole('main');
      const headings = [
        ...within(main).getAllByRole('heading', { level: 2 }),
        ...within(main).queryAllByRole('heading', { level: 3 }),
      ];
      for (const heading of headings) expect(heading.id, heading.textContent ?? '').not.toBe('');
    },
  );
});

describe('an Instance without Operator details', () => {
  it.each(['/privacy', '/terms', '/it/privacy', '/it/terms'])('has no page at %s', (path) => {
    renderLegalRoute(path, DEFAULT_INSTANCE);
    expect(screen.queryByRole('main')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
  });
});
