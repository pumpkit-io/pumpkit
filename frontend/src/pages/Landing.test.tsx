import type { InternalAxiosRequestConfig } from 'axios';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import { ThemeProvider } from '@/features/theme/ThemeProvider';
import { InstanceProvider } from '@/features/instance/InstanceProvider';
import type { Instance } from '@/lib/instance';
import { SELLS_PLANS, WITH_OPERATOR, WITH_SUPPORT_EMAIL } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { api } from '@/services/apiService';
import { billingService } from '@/services/billingService';
import { Landing } from './Landing';

const LANDING_AUTHOR_NAMES = [
  'Pieter Levels',
  'Marc Lou',
  'Danny Postma',
  'Tony Dinh',
  'Arvid Kahl',
  'Rob Walling',
  'Sahil Lavingia',
  'David Heinemeier Hansson',
  'Noah Kagan',
  'Alex Hormozi',
  'Codie Sanchez',
  'Nick Huber',
  'Sam Parr',
  'Shaan Puri',
  'Greg Isenberg',
  'Justin Welsh',
  'Dan Koe',
  'Sahil Bloom',
  'Dickie Bush',
  'Nicolas Cole',
  'Harry Dry',
  'Naval Ravikant',
  'Paul Graham',
  'George Mack',
  'Jack Butcher',
  'James Clear',
  'Morgan Housel',
  'Lenny Rachitsky',
  'Garry Tan',
  'Andrej Karpathy',
];

const originalAdapter = api.defaults.adapter;

const PRICING = 'One plan. Everything in it.';

/** Matches the paragraph whose whole text is `text`, however its words are styled. */
const paragraph = (text: string) => (_: string, element: Element | null) =>
  element?.tagName === 'P' && element.textContent === text;

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

const GITHUB_REPO_API = 'https://api.github.com/repos/pumpkit-io/pumpkit';

/** Fakes the browser's fetch of the repository from GitHub's public API. */
function fakeGitHubRepo(response: Promise<Response>) {
  const fetchFake = vi.fn((input: RequestInfo | URL) =>
    String(input) === GITHUB_REPO_API ? response : Promise.reject(new Error('Unexpected fetch')),
  );
  vi.stubGlobal('fetch', fetchFake);
  return fetchFake;
}

function gitHubRepoWithStars(stars: number) {
  return Promise.resolve(
    new Response(JSON.stringify({ stargazers_count: stars }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

/** Clicks an external link without jsdom attempting the navigation it can't do. */
function clickExternalLink(link: HTMLElement) {
  link.addEventListener('click', (event) => event.preventDefault(), { once: true });
  fireEvent.click(link);
}

const MONTHLY_PLAN = {
  key: 'pumpkit_pro_monthly',
  product_name: 'Pro',
  amount: 1900,
  currency: 'eur',
  interval: 'month',
  interval_count: 1,
};

const ANNUAL_PLAN = {
  key: 'pumpkit_pro_yearly',
  product_name: 'Pro',
  amount: 19000,
  currency: 'eur',
  interval: 'year',
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

const OFFER = {
  terms_version: '2026-10-11',
  allowance: { generations: 500, x_posts: 100, link_x_posts: 10 },
  trial: { days: 7, generations: 125, x_posts: 25, link_x_posts: 2 },
};

/** Renders the landing page as a signed-out visitor sees it at `/`. */
const WITH_ANALYTICS: Instance = {
  ...SELLS_PLANS,
  analytics: {
    key: 'phc_test',
    host: 'https://eu.i.posthog.com',
    ui_host: 'https://eu.posthog.com',
  },
};

function renderLanding(instance: Instance = SELLS_PLANS) {
  return render(
    <InstanceProvider instance={instance}>
      <ThemeProvider>
        <MemoryRouter>
          <Landing />
        </MemoryRouter>
      </ThemeProvider>
    </InstanceProvider>,
  );
}

beforeEach(() => {
  vi.mocked(track).mockClear();
  fakePlansEndpoint(200, { ...OFFER, data: [MONTHLY_PLAN, ANNUAL_PLAN] });
  fakeGitHubRepo(new Promise<Response>(() => {}));
});

afterEach(() => {
  api.defaults.adapter = originalAdapter;
  vi.unstubAllGlobals();
});

describe('Landing on an Instance that sells no Plans', () => {
  it('shows no pricing section or Pricing link and asks for no Plans', () => {
    const fetchPlans = vi.spyOn(billingService, 'fetchPlans');
    onTestFinished(() => fetchPlans.mockRestore());
    renderLanding({ ...SELLS_PLANS, sells_plans: false });

    expect(screen.queryByRole('region', { name: PRICING })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Pricing' })).not.toBeInTheDocument();
    expect(fetchPlans).not.toHaveBeenCalled();
  });
});

describe('Landing hero', () => {
  it('shows the headline and subline with no pill above them', () => {
    renderLanding();
    expect(screen.queryByText('Open source · built for X')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      /^Run your X on autopilot with Claude Code, Codex, Cursor or Gemini CLI\./,
    );
    expect(
      screen.getByText(
        'Pumpkit writes and schedules posts on X for you. Posts sound like you, or like your favorite X accounts. Use it in the web app, or use the MCP to let your agents run it.',
      ),
    ).toBeInTheDocument();
  });

  it('reads the headline once to assistive tech and shows one tool name at a time', () => {
    renderLanding();
    const [readable, visual] = Array.from(screen.getByRole('heading', { level: 1 }).children);
    expect(readable).toHaveClass('sr-only');
    expect(visual).toHaveAttribute('aria-hidden', 'true');
    expect(visual).toHaveTextContent(/^Run your\s+on autopilot with\s*Claude Code$/);
  });

  it('tracks the hero button and no longer tracks a screenshot', async () => {
    renderLanding();
    fireEvent.click(await screen.findByRole('link', { name: 'Start a 7-day trial for €0' }));
    expect(track).toHaveBeenCalledWith('landing_hero_cta_clicked');
    expect(vi.mocked(track).mock.calls.map(([event]) => event)).not.toContain(
      'landing_hero_screenshot_viewed',
    );
  });
});

/** Makes `matchMedia` match only the given queries. */
function matchMediaQueries(matching: string[]) {
  const spy = vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: matching.includes(query),
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  );
  onTestFinished(() => spy.mockRestore());
}

describe('Landing launch video', () => {
  beforeEach(() => {
    // jsdom has no media: play and pause only fire the events a browser would.
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function (
      this: HTMLMediaElement,
    ) {
      this.dispatchEvent(new Event('play'));
      return Promise.resolve();
    });
    const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function (
      this: HTMLMediaElement,
    ) {
      this.dispatchEvent(new Event('pause'));
    });
    onTestFinished(() => {
      play.mockRestore();
      pause.mockRestore();
    });
  });

  function launchVideo() {
    const player = screen.getByRole('group', { name: 'Launch video' });
    const video = player.querySelector('video')!;
    return { player, video };
  }

  function loadMetadata(video: HTMLVideoElement, duration = 66) {
    Object.defineProperty(video, 'duration', { configurable: true, value: duration });
    fireEvent(video, new Event('loadedmetadata'));
  }

  it('waits muted on its poster with a play button, loading only metadata', () => {
    renderLanding();
    const { player, video } = launchVideo();
    expect(video).toHaveAttribute('preload', 'metadata');
    expect(video.muted).toBe(true);
    expect(video).toHaveAttribute('poster');
    expect(video.querySelector('track')).toBeNull();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(within(player).getByRole('button', { name: 'Play video' })).toBeInTheDocument();
    expect(within(player).getByRole('button', { name: 'Sound on' })).toBeInTheDocument();
  });

  it('autoplays in view on a desktop-sized viewport', () => {
    matchMediaQueries(['(min-width: 1024px)']);
    renderLanding();
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith('landing_video_played', { trigger: 'autoplay' });
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
  });

  it('does not autoplay when the visitor prefers reduced motion', () => {
    matchMediaQueries(['(min-width: 1024px)', '(prefers-reduced-motion: reduce)']);
    renderLanding();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Play video' })).toBeInTheDocument();
  });

  it('plays and pauses from its buttons, tracking the first play', () => {
    renderLanding();
    const { player } = launchVideo();
    fireEvent.click(within(player).getByRole('button', { name: 'Play video' }));
    expect(track).toHaveBeenCalledWith('landing_video_played', { trigger: 'visitor' });
    expect(within(player).queryByRole('button', { name: 'Play video' })).not.toBeInTheDocument();

    fireEvent.click(within(player).getByRole('button', { name: 'Pause' }));
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalledTimes(1);
    fireEvent.click(within(player).getByRole('button', { name: 'Play' }));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2);
    expect(
      vi.mocked(track).mock.calls.filter(([event]) => event === 'landing_video_played'),
    ).toHaveLength(1);
  });

  it('toggles play with Space and K while the player has focus', () => {
    renderLanding();
    const { player } = launchVideo();
    fireEvent.keyDown(player, { key: ' ' });
    expect(within(player).getByRole('button', { name: 'Pause' })).toBeInTheDocument();
    fireEvent.keyDown(player, { key: 'k' });
    expect(within(player).getByRole('button', { name: 'Play' })).toBeInTheDocument();
  });

  it('turns the sound on and off', () => {
    renderLanding();
    const { player, video } = launchVideo();
    fireEvent.click(within(player).getByRole('button', { name: 'Sound on' }));
    expect(video.muted).toBe(false);
    expect(track).toHaveBeenCalledWith('landing_video_sound_turned_on');

    fireEvent.click(within(player).getByRole('button', { name: 'Sound off' }));
    expect(video.muted).toBe(true);
    expect(
      vi.mocked(track).mock.calls.filter(([event]) => event === 'landing_video_sound_turned_on'),
    ).toHaveLength(1);
  });

  it('scrubs with the arrow keys and shows the current time and the total', () => {
    renderLanding();
    const { player, video } = launchVideo();
    loadMetadata(video);
    expect(within(player).getByText('0:00 / 1:06')).toBeInTheDocument();

    const scrubber = within(player).getByRole('slider', { name: 'Seek' });
    fireEvent.keyDown(scrubber, { key: 'ArrowRight' });
    fireEvent.keyDown(scrubber, { key: 'ArrowRight' });
    expect(scrubber).toHaveAttribute('aria-valuenow', '2');
    expect(scrubber).toHaveAttribute('aria-valuetext', '0:02 of 1:06');
    expect(within(player).getByText('0:02 / 1:06')).toBeInTheDocument();
    expect(track).toHaveBeenCalledWith('landing_video_scrubbed');

    fireEvent.keyDown(scrubber, { key: 'ArrowLeft' });
    expect(scrubber).toHaveAttribute('aria-valuenow', '1');
  });

  it('ends on Watch again, which plays it from the start', () => {
    renderLanding();
    const { player, video } = launchVideo();
    loadMetadata(video);
    fireEvent.click(within(player).getByRole('button', { name: 'Play video' }));
    fireEvent(video, new Event('ended'));

    fireEvent.click(within(player).getByRole('button', { name: 'Watch again' }));
    expect(track).toHaveBeenCalledWith('landing_video_watched_again');
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(2);
    expect(within(player).queryByRole('button', { name: 'Watch again' })).not.toBeInTheDocument();
  });

  it('labels the fullscreen button', () => {
    renderLanding();
    const { player } = launchVideo();
    expect(within(player).getByRole('button', { name: 'Full screen' })).toBeInTheDocument();
  });

  it('says so on its poster when the file fails to load', () => {
    renderLanding();
    const { player, video } = launchVideo();
    fireEvent.error(video.querySelector('source[type="video/mp4"]')!);
    expect(within(player).getByText("The video couldn't load.")).toBeInTheDocument();
    expect(within(player).queryByRole('button', { name: 'Play video' })).not.toBeInTheDocument();
  });
});

describe('Landing landmarks', () => {
  it('keeps the header outside one main landmark that holds hero, authors and pricing', () => {
    renderLanding();
    const main = screen.getByRole('main');
    expect(within(main).queryByRole('banner')).not.toBeInTheDocument();
    expect(within(main).getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(
      within(main).getByRole('region', { name: 'Write in the style of accounts like these.' }),
    ).toBeInTheDocument();
    expect(within(main).getByRole('region', { name: PRICING })).toBeInTheDocument();
  });
});

describe('Landing header', () => {
  it("names the Instance's app in the header", () => {
    renderLanding({ ...SELLS_PLANS, app_name: 'acmeWriter' });
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('link', { name: 'acmeWriter home' })).toBeInTheDocument();
  });

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

  it('sends every Get started and Trial button to the sign-in page', async () => {
    renderLanding();
    await screen.findByRole('link', { name: 'Start a 7-day trial for €0' });
    const signInLinks = screen.getAllByRole('link', {
      name: /^(get started|start for €0|start a 7-day trial for €0)$/i,
    });
    expect(signInLinks.map((link) => link.textContent)).toEqual(
      expect.arrayContaining(['Start for €0', 'Start a 7-day trial for €0', 'Get started']),
    );
    for (const link of signInLinks) expect(link).toHaveAttribute('href', '/login');
  });

  it('names the Trial and its price in the hero and nav buttons once the catalogue loads', async () => {
    renderLanding();
    expect(
      await screen.findByRole('link', { name: 'Start a 7-day trial for €0' }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole('banner')).getByRole('link', { name: 'Start for €0' }),
    ).toBeVisible();
  });

  it('keeps Get started on both buttons when the Instance offers no Trial', async () => {
    fakePlansEndpoint(200, { ...OFFER, trial: null, data: [MONTHLY_PLAN, ANNUAL_PLAN] });
    renderLanding();
    await screen.findByRole('list', { name: 'Included' });
    expect(screen.queryByRole('link', { name: /trial|for €0/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Get started' }).length).toBeGreaterThanOrEqual(3);
  });

  it('tracks the logo and the desktop links with their surface', () => {
    renderLanding();
    const header = screen.getByRole('banner');
    fireEvent.click(within(header).getByRole('link', { name: 'Pumpkit home' }));
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

  it('closes on Escape and tracks it like the close button', () => {
    renderLanding();
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    expect(screen.getByRole('navigation', { name: 'Menu' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('navigation', { name: 'Menu' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open menu' })).toBeInTheDocument();
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
    const section = screen.getByRole('region', {
      name: 'Write in the style of accounts like these.',
    });
    expect(section).toHaveAttribute('id', 'authors');
    const hero = screen.getByRole('heading', { level: 1 });
    const pricing = document.getElementById('pricing');
    expect(hero.compareDocumentPosition(section)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(section.compareDocumentPosition(pricing!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('has no small label above the heading', () => {
    renderLanding();
    const section = screen.getByRole('region', {
      name: 'Write in the style of accounts like these.',
    });
    expect(within(section).queryByText('Learn from the best on X')).not.toBeInTheDocument();
  });

  it('shows the 30 accounts once each, named and unlinked, without handles', () => {
    renderLanding();
    const section = screen.getByRole('region', {
      name: 'Write in the style of accounts like these.',
    });
    const photos = within(section).getAllByRole('img');
    expect(photos).toHaveLength(30);
    expect(photos.map((photo) => photo.getAttribute('alt'))).toEqual(LANDING_AUTHOR_NAMES);
    const sources = photos.map((photo) => photo.getAttribute('src'));
    sources.forEach((src) => expect(src).toMatch(/\.webp$/));
    expect(new Set(sources).size).toBe(30);
    expect(within(section).queryByRole('link')).not.toBeInTheDocument();
    expect(section).not.toHaveTextContent('@');
    expect(section).not.toHaveTextContent('levelsio');
  });

  it('tracks the section coming into view once', () => {
    renderLanding();
    const calls = vi
      .mocked(track)
      .mock.calls.filter(([event]) => event === 'landing_authors_section_viewed');
    expect(calls).toEqual([['landing_authors_section_viewed']]);
  });
});

describe('Landing footer', () => {
  it('names the Operator with its VAT ID on one copyright line for the current year', () => {
    vi.setSystemTime(new Date('2027-03-01T12:00:00Z'));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    renderLanding(WITH_OPERATOR);
    const footer = screen.getByRole('contentinfo');
    expect(
      within(footer).getByText('© 2027 Example S.R.L. · VAT ID IT01234567890'),
    ).toBeInTheDocument();
  });

  it('names only the Operator when it has no VAT ID', () => {
    vi.setSystemTime(new Date('2027-03-01T12:00:00Z'));
    onTestFinished(() => {
      vi.useRealTimers();
    });
    renderLanding({ ...WITH_OPERATOR, operator: { name: 'Example S.R.L.', vat_id: null } });
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText('© 2027 Example S.R.L.')).toBeInTheDocument();
    expect(within(footer).queryByText(/VAT ID/)).not.toBeInTheDocument();
  });

  it('links Company details to the Operator section of the Terms', () => {
    renderLanding(WITH_OPERATOR);
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('link', { name: 'Company details' })).toHaveAttribute(
      'href',
      '/terms#operator',
    );
  });

  it('offers Cookie settings', () => {
    renderLanding({ ...WITH_OPERATOR, analytics: WITH_ANALYTICS.analytics });
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
  });

  it('offers no Cookie settings on an Instance without analytics', () => {
    renderLanding(WITH_OPERATOR);
    const footer = screen.getByRole('contentinfo');
    expect(
      within(footer).queryByRole('button', { name: 'Cookie settings' }),
    ).not.toBeInTheDocument();
  });

  it('links to the Privacy Policy, the Terms and the support address', () => {
    renderLanding(WITH_OPERATOR);
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('link', { name: 'Privacy Policy' })).toHaveAttribute(
      'href',
      '/privacy',
    );
    expect(within(footer).getByRole('link', { name: 'Terms' })).toHaveAttribute('href', '/terms');
    expect(within(footer).getByRole('link', { name: 'help@example.org' })).toHaveAttribute(
      'href',
      'mailto:help@example.org',
    );
  });

  it('shows only Cookie settings on an Instance with analytics but no Operator details', () => {
    renderLanding(WITH_ANALYTICS);
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('button', { name: 'Cookie settings' })).toBeInTheDocument();
    expect(within(footer).queryByRole('link')).not.toBeInTheDocument();
    expect(within(footer).queryByText(/©/)).not.toBeInTheDocument();
  });

  it('shows only the support address on an Instance with it but no Operator details', () => {
    renderLanding(WITH_SUPPORT_EMAIL);
    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByRole('link', { name: 'help@example.org' })).toHaveAttribute(
      'href',
      'mailto:help@example.org',
    );
    expect(within(footer).queryByRole('link', { name: 'Terms' })).not.toBeInTheDocument();
    expect(within(footer).queryByRole('link', { name: 'Company details' })).not.toBeInTheDocument();
    expect(within(footer).queryByText(/©/)).not.toBeInTheDocument();
  });

  it('has no footer on an Instance with neither Operator details nor analytics', () => {
    renderLanding();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
  });
});

describe('Landing pricing', () => {
  it('opens with its heading and no label or subline around it', () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    expect(pricing).toHaveAttribute('id', 'pricing');
    expect(within(pricing).getByRole('heading', { level: 2 })).toHaveTextContent(PRICING);
    expect(within(pricing).queryByText('Pricing')).not.toBeInTheDocument();
    expect(within(pricing).queryByText('[Pricing subline]')).not.toBeInTheDocument();
  });

  it('says Loading… until the Plans arrive', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    expect(within(pricing).getByText('Loading…')).toBeInTheDocument();
    await within(pricing).findByRole('radiogroup', { name: 'Billing interval' });
    expect(within(pricing).queryByText('Loading…')).not.toBeInTheDocument();
  });

  it('starts on Monthly with the monthly price', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    const toggle = await within(pricing).findByRole('radiogroup', { name: 'Billing interval' });
    expect(within(toggle).getByRole('radio', { name: 'Monthly' })).toBeChecked();
    expect(within(toggle).getByRole('radio', { name: 'Annual Save 17%' })).not.toBeChecked();
    expect(within(pricing).getByText(paragraph('€19 a month'))).toBeInTheDocument();
    expect(within(pricing).queryByText(/a year/)).not.toBeInTheDocument();
  });

  it('switches to the yearly charge with its monthly equivalent under it, and back', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    fireEvent.click(await within(pricing).findByRole('radio', { name: 'Annual Save 17%' }));

    const yearly = within(pricing).getByText(paragraph('€190 a year'));
    const perMonth = within(pricing).getByText('€15.83 a month, billed yearly');
    expect(yearly.compareDocumentPosition(perMonth)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(within(pricing).queryByText(paragraph('€19 a month'))).not.toBeInTheDocument();
    expect(track).toHaveBeenCalledWith('landing_pricing_toggle_switched', { interval: 'annual' });

    fireEvent.click(within(pricing).getByRole('radio', { name: 'Monthly' }));
    expect(within(pricing).getByText(paragraph('€19 a month'))).toBeInTheDocument();
    expect(within(pricing).queryByText(/billed yearly/)).not.toBeInTheDocument();
    expect(track).toHaveBeenCalledWith('landing_pricing_toggle_switched', { interval: 'monthly' });
  });

  it('works the saving out from the two prices', async () => {
    fakePlansEndpoint(200, {
      ...OFFER,
      data: [
        { ...ANNUAL_PLAN, amount: 9000 },
        { ...MONTHLY_PLAN, amount: 1000 },
      ],
    });
    renderLanding();
    expect(await screen.findByRole('radio', { name: 'Annual Save 25%' })).toBeInTheDocument();
  });

  it('puts the Trial line under the price, outside the offer list', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    const list = await within(pricing).findByRole('list', { name: 'Included' });
    const price = within(pricing).getByText(paragraph('€19 a month'));
    const trial = within(pricing).getByText(
      '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.',
    );
    expect(price.compareDocumentPosition(trial)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(trial.compareDocumentPosition(list)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(list).not.toHaveTextContent(/trial/);
  });

  it('lists what the Plan gives, including scheduling and the AI tools', async () => {
    renderLanding();
    const list = await screen.findByRole('list', { name: 'Included' });
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      '500 post generations a month.',
      'Publish 100 X posts a month, up to 10 of them with a link.',
      'Write in the voice of your favorite X creators.',
      'Schedule posts and threads to X.',
      'Use it from Claude Code, Codex, Cursor or Gemini CLI.',
    ]);
  });

  it.each([
    ['About generations', 'Every prompt to generate or refine a post counts as one generation.'],
    [
      'About X posts',
      'Scheduled posts and posts you post now both count. For threads, each post in the thread counts.',
    ],
    [
      'About AI tools',
      'Pumpkit is an MCP server: any AI tool that supports MCP can use it to write, revise and schedule posts.',
    ],
  ])('explains %s behind an info button', async (name, text) => {
    renderLanding();
    fireEvent.click(await screen.findByRole('button', { name }));
    expect(await screen.findByRole('dialog', { name })).toHaveTextContent(text);
  });

  it('leaves out the Trial and the lines of empty caps', async () => {
    fakePlansEndpoint(200, {
      ...OFFER,
      data: [MONTHLY_PLAN, ANNUAL_PLAN],
      allowance: { generations: 500, x_posts: null, link_x_posts: null },
      trial: null,
    });
    renderLanding();
    const list = await screen.findByRole('list', { name: 'Included' });
    expect(
      within(list)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      '500 post generations a month.',
      'Write in the voice of your favorite X creators.',
      'Schedule posts and threads to X.',
      'Use it from Claude Code, Codex, Cursor or Gemini CLI.',
    ]);
    expect(screen.queryByText(/free trial/)).not.toBeInTheDocument();
  });

  it("lists each Plan's price with no toggle without one monthly and one annual Plan", async () => {
    fakePlansEndpoint(200, { ...OFFER, data: [MONTHLY_PLAN, QUARTERLY_PLAN] });
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    await within(pricing).findByRole('list', { name: 'Included' });
    expect(within(pricing).queryByRole('radiogroup')).not.toBeInTheDocument();
    const monthly = within(pricing).getByText(paragraph('€19 a month'));
    const quarterly = within(pricing).getByText(paragraph('€24 every 3 months'));
    expect(monthly.compareDocumentPosition(quarterly)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(
      within(pricing).getByText(
        '7-day free trial: 125 generations and 25 X posts, up to 2 with a link.',
      ),
    ).toBeInTheDocument();
  });

  it('shows the single price of a lone Plan with no toggle', async () => {
    fakePlansEndpoint(200, { ...OFFER, data: [ANNUAL_PLAN] });
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    expect(await within(pricing).findByText(paragraph('€190 a year'))).toBeInTheDocument();
    expect(within(pricing).queryByRole('radiogroup')).not.toBeInTheDocument();
  });

  it('says so when the Plans cannot load', async () => {
    fakePlansEndpoint(502, { detail: 'Billing is unavailable right now.', error_id: 'e' });
    renderLanding();
    expect(
      await screen.findByText("Pricing couldn't load. Refresh the page to try again."),
    ).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Included' })).not.toBeInTheDocument();
  });

  it('shows a fallback when there are no Plans', async () => {
    fakePlansEndpoint(200, { ...OFFER, data: [] });
    renderLanding();
    expect(await screen.findByText('Pricing is coming soon.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Included' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
  });

  it('ends with a Get started button to the sign-in page and no note under it', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    await within(pricing).findByRole('list', { name: 'Included' });
    const cta = within(pricing).getByRole('link', { name: 'Get started' });
    expect(cta).toHaveAttribute('href', '/login');
    expect(pricing.textContent?.trimEnd().endsWith('Get started')).toBe(true);

    fireEvent.click(cta);
    expect(track).toHaveBeenCalledWith('landing_pricing_cta_clicked');
  });

  it('tracks the section once and the Plan shown on the card once', async () => {
    renderLanding();
    await screen.findByRole('list', { name: 'Included' });
    const calls = vi.mocked(track).mock.calls;
    expect(calls.filter(([event]) => event === 'landing_pricing_section_viewed')).toEqual([
      ['landing_pricing_section_viewed'],
    ]);
    expect(calls.filter(([event]) => event === 'landing_pricing_plan_viewed')).toEqual([
      ['landing_pricing_plan_viewed', { plan_key: 'pumpkit_pro_monthly' }],
    ]);
  });

  it('tracks the other Plan once, the first time the visitor switches to it', async () => {
    renderLanding();
    const pricing = screen.getByRole('region', { name: PRICING });
    await within(pricing).findByRole('radiogroup', { name: 'Billing interval' });
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Annual Save 17%' }));
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Monthly' }));
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Annual Save 17%' }));
    const viewed = vi
      .mocked(track)
      .mock.calls.filter(([event]) => event === 'landing_pricing_plan_viewed');
    expect(viewed).toEqual([
      ['landing_pricing_plan_viewed', { plan_key: 'pumpkit_pro_monthly' }],
      ['landing_pricing_plan_viewed', { plan_key: 'pumpkit_pro_yearly' }],
    ]);
  });
});

describe('Landing GitHub button', () => {
  it('links to the repository without a star count and without calling GitHub', () => {
    const fetchFake = fakeGitHubRepo(gitHubRepoWithStars(1234));
    renderLanding();
    const header = screen.getByRole('banner');
    expect(within(header).getByRole('link', { name: 'GitHub' })).toHaveAttribute(
      'href',
      'https://github.com/pumpkit-io/pumpkit',
    );
    expect(within(header).queryByText(/1\.2k/)).not.toBeInTheDocument();
    expect(fetchFake).not.toHaveBeenCalled();
  });

  it('tracks a desktop click with its surface', () => {
    renderLanding();
    clickExternalLink(within(screen.getByRole('banner')).getByRole('link', { name: 'GitHub' }));
    expect(track).toHaveBeenCalledWith('landing_nav_github_clicked', { surface: 'desktop' });
  });

  it('sits in the mobile menu, and tracks a tap as mobile', () => {
    renderLanding();
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    const menu = screen.getByRole('navigation', { name: 'Menu' });
    const button = within(menu).getByRole('link', { name: 'GitHub' });
    expect(button).toHaveAttribute('href', 'https://github.com/pumpkit-io/pumpkit');

    clickExternalLink(button);
    expect(track).toHaveBeenCalledWith('landing_nav_github_clicked', { surface: 'mobile' });
    expect(screen.queryByRole('navigation', { name: 'Menu' })).not.toBeInTheDocument();
  });
});

describe('Landing open source', () => {
  const heading = 'Read every line. Run it yourself.';

  it.each([
    ['an Instance that sells Plans', SELLS_PLANS],
    ['an Instance that sells no Plans', { ...SELLS_PLANS, sells_plans: false }],
  ])('says Pumpkit is open source on %s, last in the main landmark', (_, instance) => {
    renderLanding(instance);
    const section = within(screen.getByRole('main')).getByRole('region', { name: heading });
    expect(within(section).getByRole('heading', { level: 2 })).toHaveTextContent(heading);
    expect(
      within(section).getByText(
        'Pumpkit is open source under AGPL-3.0. Self-host it on your own server, or use pumpkit.io and skip the setup.',
      ),
    ).toBeInTheDocument();
    const authors = screen.getByRole('region', {
      name: 'Write in the style of accounts like these.',
    });
    expect(authors.compareDocumentPosition(section)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getByRole('main').lastElementChild).toBe(section);
  });

  it('links to the repository and the self-hosting guide, tracking each', () => {
    renderLanding();
    const section = screen.getByRole('region', { name: heading });
    const github = within(section).getByRole('link', { name: 'View on GitHub' });
    const guide = within(section).getByRole('link', { name: 'Self-hosting guide' });
    expect(github).toHaveAttribute('href', 'https://github.com/pumpkit-io/pumpkit');
    expect(guide).toHaveAttribute(
      'href',
      'https://github.com/pumpkit-io/pumpkit/blob/main/docs/self-hosting.md',
    );

    clickExternalLink(github);
    expect(track).toHaveBeenCalledWith('landing_open_source_github_clicked');
    clickExternalLink(guide);
    expect(track).toHaveBeenCalledWith('landing_open_source_self_hosting_clicked');
  });

  it('tracks the section coming into view once', () => {
    renderLanding();
    const calls = vi
      .mocked(track)
      .mock.calls.filter(([event]) => event === 'landing_open_source_section_viewed');
    expect(calls).toEqual([['landing_open_source_section_viewed']]);
  });
});

describe('Landing mascots', () => {
  const mascots = () => Array.from(document.querySelectorAll<HTMLElement>('[data-mascot]'));

  async function pricingCard() {
    const pricing = screen.getByRole('region', { name: PRICING });
    await within(pricing).findByRole('radiogroup', { name: 'Billing interval' });
    return pricing;
  }

  it('shows four mascots beside sections, none in the hero, all hidden from assistive technology', async () => {
    renderLanding();
    await pricingCard();
    expect(mascots().map((mascot) => mascot.dataset.mascot)).toEqual([
      'costume_change',
      'tada',
      'detective',
      'doze_off',
    ]);
    mascots().forEach((mascot) => expect(mascot).toHaveAttribute('aria-hidden', 'true'));
    const hero = screen.getByRole('heading', { level: 1 }).closest('section')!;
    expect(hero.querySelector('[data-mascot]')).toBeNull();
  });

  it('celebrates only the first switch to Annual on the pricing card', async () => {
    renderLanding();
    const pricing = await pricingCard();
    const tada = pricing.querySelector<HTMLElement>('[data-mascot="tada"]')!;
    expect(tada).toHaveAttribute('data-state', 'still');

    vi.useFakeTimers();
    onTestFinished(() => {
      vi.useRealTimers();
    });
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Annual Save 17%' }));
    expect(tada).toHaveAttribute('data-state', 'playing');

    // Each frame's timer starts once React renders the frame before it, so time passes in steps.
    for (let elapsed = 0; elapsed < 10_000; elapsed += 100) act(() => vi.advanceTimersByTime(100));
    expect(tada).toHaveAttribute('data-state', 'still');
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Monthly' }));
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Annual Save 17%' }));
    expect(tada).toHaveAttribute('data-state', 'still');
  });

  it('lets the footer mascot nod off and stay asleep, wakes it on hover and lets it nod off again', () => {
    vi.useFakeTimers();
    onTestFinished(() => {
      vi.useRealTimers();
    });
    renderLanding({ ...SELLS_PLANS, sells_plans: false });
    const footer = document.querySelector<HTMLElement>('[data-mascot="doze_off"]')!;
    // Each frame's timer starts once React renders the frame before it, so time passes in steps.
    const wait = (ms: number) => {
      for (let elapsed = 0; elapsed < ms; elapsed += 100) act(() => vi.advanceTimersByTime(100));
    };
    expect(footer).toHaveAttribute('data-state', 'still');

    wait(30_000);
    expect(footer).toHaveAttribute('data-state', 'rested');

    fireEvent.mouseEnter(footer);
    expect(footer).toHaveAttribute('data-state', 'still');
    wait(30_000);
    expect(footer).toHaveAttribute('data-state', 'still');

    fireEvent.mouseLeave(footer);
    wait(30_000);
    expect(footer).toHaveAttribute('data-state', 'rested');
  });

  it('keeps every mascot still when the visitor prefers reduced motion', async () => {
    matchMediaQueries(['(prefers-reduced-motion: reduce)']);
    renderLanding();
    const pricing = await pricingCard();
    fireEvent.click(within(pricing).getByRole('radio', { name: 'Annual Save 17%' }));
    expect(mascots()).toHaveLength(4);
    mascots().forEach((mascot) => expect(mascot).toHaveAttribute('data-state', 'still'));
  });
});
