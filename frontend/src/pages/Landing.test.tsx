import type { InternalAxiosRequestConfig } from 'axios';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { track } from '@/lib/analytics';
import { APP_NAME } from '@/lib/app';
import { api } from '@/services/apiService';
import { Landing } from './Landing';

const originalAdapter = api.defaults.adapter;

/** Fakes `GET /billing/plans` at the axios adapter. */
function fakePlansEndpoint(status: number, data: unknown) {
  api.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
    const found = config.url === '/billing/plans';
    const response = {
      data: found ? data : { detail: 'Not Found' },
      status: found ? status : 404,
      statusText: '',
      headers: {},
      config,
    };
    if (response.status >= 400) {
      throw Object.assign(new Error(`Request failed with status ${response.status}`), {
        isAxiosError: true,
        response,
        config,
      });
    }
    return response;
  };
}

const MONTHLY_PLAN = {
  key: 'pumpkit_pro_monthly',
  product_name: 'Pro',
  amount: 900,
  currency: 'eur',
  interval: 'month',
  interval_count: 1,
};

const QUARTERLY_PLAN = {
  key: 'pumpkit_pro_quarterly',
  product_name: 'Pro quarterly',
  amount: 2400,
  currency: 'eur',
  interval: 'month',
  interval_count: 3,
};

/** Renders the landing page as a signed-out visitor sees it at `/`. */
function renderLanding() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <Landing />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  vi.mocked(track).mockClear();
  fakePlansEndpoint(200, { data: [MONTHLY_PLAN, QUARTERLY_PLAN] });
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
});

describe('Landing hero', () => {
  it('shows the badge, headline and subline', () => {
    renderLanding();
    expect(screen.getByText('Open source · built for X')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      /^Your ideas, in the style of the authors you admire\.$/,
    );
    expect(
      screen.getByText(
        'Write a brief, pick up to three X authors to learn style from, and get a post ready to paste. Not quite right? Say what to change and get a new version.',
      ),
    ).toBeInTheDocument();
  });

  it('holds a visible placeholder in the screenshot slot', () => {
    renderLanding();
    expect(screen.getByText('[Product screenshot]')).toBeInTheDocument();
  });

  it('tracks the hero button and the screenshot coming into view', () => {
    renderLanding();
    expect(track).toHaveBeenCalledWith('landing_hero_screenshot_viewed');
    fireEvent.click(screen.getByRole('link', { name: 'Start writing' }));
    expect(track).toHaveBeenCalledWith('landing_hero_cta_clicked');
  });
});

describe('Landing header', () => {
  it('links the Authors and Pricing anchors to their sections', () => {
    renderLanding();
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('link', { name: 'Authors' })).toHaveAttribute(
      'href',
      '#authors',
    );
    expect(within(header).getByRole('link', { name: 'Pricing' })).toHaveAttribute(
      'href',
      '#pricing',
    );
  });

  it('sends every Get started and Start writing button to the sign-in page', () => {
    renderLanding();
    const signInLinks = screen.getAllByRole('link', { name: /^(get started|start writing)$/i });
    expect(signInLinks.map((link) => link.textContent)).toEqual(
      expect.arrayContaining(['Get started', 'Start writing']),
    );
    for (const link of signInLinks) expect(link).toHaveAttribute('href', '/login');
  });

  it('tracks the logo and the desktop links with their surface', () => {
    renderLanding();
    const header = screen.getByRole('banner');
    fireEvent.click(within(header).getByRole('link', { name: `${APP_NAME} home` }));
    fireEvent.click(within(header).getByRole('link', { name: 'Authors' }));
    fireEvent.click(within(header).getByRole('link', { name: 'Pricing' }));
    fireEvent.click(within(header).getByRole('link', { name: 'Get started' }));
    expect(track).toHaveBeenCalledWith('landing_nav_logo_clicked');
    expect(track).toHaveBeenCalledWith('landing_nav_authors_clicked', { surface: 'desktop' });
    expect(track).toHaveBeenCalledWith('landing_nav_pricing_clicked', { surface: 'desktop' });
    expect(track).toHaveBeenCalledWith('landing_nav_get_started_clicked', { surface: 'desktop' });
  });
});

describe('Landing mobile menu', () => {
  it('opens and closes from its button', () => {
    renderLanding();
    expect(screen.queryByRole('navigation', { name: 'Menu' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    const menu = screen.getByRole('navigation', { name: 'Menu' });
    expect(within(menu).getByRole('link', { name: 'Authors' })).toHaveAttribute('href', '#authors');
    expect(within(menu).getByRole('link', { name: 'Pricing' })).toHaveAttribute('href', '#pricing');
    expect(within(menu).getByRole('link', { name: 'Get started' })).toHaveAttribute(
      'href',
      '/login',
    );
    expect(track).toHaveBeenCalledWith('landing_mobile_menu_opened');

    fireEvent.click(screen.getByRole('button', { name: 'Close menu' }));
    expect(screen.queryByRole('navigation', { name: 'Menu' })).not.toBeInTheDocument();
    expect(track).toHaveBeenCalledWith('landing_mobile_menu_closed');
  });

  it.each([
    ['Authors', 'landing_nav_authors_clicked'],
    ['Pricing', 'landing_nav_pricing_clicked'],
    ['Get started', 'landing_nav_get_started_clicked'],
  ])('closes when %s is tapped and tracks it as mobile', (name, event) => {
    renderLanding();
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    const menu = screen.getByRole('navigation', { name: 'Menu' });
    fireEvent.click(within(menu).getByRole('link', { name }));
    expect(screen.queryByRole('navigation', { name: 'Menu' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open menu' })).toBeInTheDocument();
    expect(track).toHaveBeenCalledWith(event, { surface: 'mobile' });
    expect(track).toHaveBeenCalledWith('landing_mobile_menu_closed');
  });
});

describe('Landing authors', () => {
  it('sits between the hero and pricing under the #authors anchor', () => {
    renderLanding();
    const section = screen.getByRole('region', { name: 'Pick the authors whose style you want.' });
    expect(section).toHaveAttribute('id', 'authors');
    expect(within(section).getByText('Learn from the best on X')).toBeInTheDocument();
    const hero = screen.getByRole('heading', { level: 1 });
    const pricing = document.getElementById('pricing');
    expect(hero.compareDocumentPosition(section)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(section.compareDocumentPosition(pricing!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('lists the placeholder author chips once, in order', () => {
    renderLanding();
    const list = screen.getByRole('list', { name: 'Authors' });
    const chips = within(list).getAllByRole('listitem');
    expect(chips.length).toBeGreaterThan(0);
    chips.forEach((chip, index) => expect(chip).toHaveTextContent(`[Author ${index + 1}]`));
  });

  it('tracks the section coming into view once', () => {
    renderLanding();
    const calls = vi
      .mocked(track)
      .mock.calls.filter(([event]) => event === 'landing_authors_section_viewed');
    expect(calls).toEqual([['landing_authors_section_viewed']]);
  });
});
