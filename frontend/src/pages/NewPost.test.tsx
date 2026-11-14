import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';

vi.mock('@/services/userService', () => ({
  userService: {
    fetchProfile: vi.fn().mockResolvedValue({
      id: 'user_01HZX',
      email: 'ada@example.com',
      firstName: 'Ada',
      lastName: 'Lovelace',
      avatarUrl: null,
    }),
    updateProfile: vi.fn(),
  },
}));
vi.mock('@/services/billingService', () => ({
  billingService: {
    fetchBillingMe: vi.fn(),
    fetchPlans: vi.fn().mockResolvedValue({
      plans: [],
      couponsEnabled: false,
      termsVersion: '2026-10-11',
      allowance: { generations: null, xPosts: null, linkXPosts: null },
      trial: null,
    }),
    openBillingPortal: vi.fn(),
    startTopUpCheckout: vi.fn(),
    subscribeNow: vi.fn(),
  },
}));
vi.mock('@/services/inspirationAuthorService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/inspirationAuthorService')>()),
  inspirationAuthorService: {
    list: vi.fn(),
    add: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
  },
}));
vi.mock('@/services/positioningService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/positioningService')>()),
  positioningService: {
    get: vi.fn().mockResolvedValue({ text: 'I post about bootstrapping.', canDraft: true }),
    save: vi.fn(),
    draft: vi.fn(),
  },
}));
vi.mock('@/services/postService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/postService')>()),
  postService: {
    list: vi.fn().mockResolvedValue({
      posts: [],
      counts: { draft: 0, scheduled: 0, published: 0, failed: 0 },
      nextOffset: null,
    }),
    get: vi.fn(),
    addVersion: vi.fn(),
  },
}));
vi.mock('@/services/briefService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/briefService')>()),
  briefService: {
    plan: vi.fn(),
    get: vi.fn(),
    write: vi.fn(),
    recent: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('@/services/xConnectionService', () => ({
  xConnectionService: {
    get: vi.fn(),
    startAuthorization: vi.fn(),
    complete: vi.fn(),
    disconnect: vi.fn(),
  },
}));
vi.mock('@/services/scheduledPostService', () => ({
  scheduledPostService: {
    pastCommunities: vi.fn().mockResolvedValue([]),
    postNow: vi.fn(),
    schedule: vi.fn(),
    lookUpCommunity: vi.fn(),
  },
}));
vi.mock('@/services/usageService', () => ({ usageService: { get: vi.fn() } }));
vi.mock('@/lib/navigation', () => ({ hardRedirect: vi.fn(), redirectTo: vi.fn() }));
vi.mock('@/lib/confetti', () => ({ fireSuccessConfetti: vi.fn() }));
vi.mock('@/lib/analytics', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/analytics')>()),
  track: vi.fn(),
}));

import type { Instance } from '@/lib/instance';
import { SELLS_PLANS } from '@/features/instance/testInstances';
import { track } from '@/lib/analytics';
import { RECENT_BRIEFS_POLL_MS } from '@/features/briefs/RecentBriefs';
import { redirectTo } from '@/lib/navigation';
import { billingService } from '@/services/billingService';
import { inspirationAuthorService } from '@/services/inspirationAuthorService';
import { positioningService } from '@/services/positioningService';
import { briefService, type Brief, type RecentBrief } from '@/services/briefService';
import { postService, type PostDetail } from '@/services/postService';
import { usageService } from '@/services/usageService';
import { xConnectionService } from '@/services/xConnectionService';
import {
  LEVELSIO,
  NOT_SUBSCRIBED,
  PAULG,
  SUBSCRIBED,
  allowanceUsedUp,
  apiError,
  currentPath,
  renderSignedIn,
  usageWith,
} from './testing/signedInApp';

function renderNewPost(state?: unknown, instance: Instance = SELLS_PLANS) {
  return renderSignedIn('/new', { state, instance });
}

async function writer() {
  return within(await screen.findByRole('region', { name: "What's the post about?" }));
}

function postWith(final: string): PostDetail {
  return {
    id: 'post_01',
    brief: 'ship small things',
    briefId: 'brief_01',
    placeInBrief: { position: 1, postCount: 1, previousPostId: null, nextPostId: null },
    plan: null,
    text: {
      format: 'post',
      firstReply: false,
      parts: [{ text: final, charCount: final.length, charLimit: 280 }],
      versionNumber: 1,
      edited: false,
    },
    versions: [
      {
        id: 'version_attempt_01',
        number: 1,
        feedback: null,
        format: 'post',
        firstReply: false,
        parts: [{ text: final, charCount: final.length, charLimit: 280 }],
        createdAt: '2026-10-10T12:00:30Z',
      },
    ],
    status: 'draft',
    writing: false,
    failedFeedback: null,
    scheduledPost: null,
    textMedia: [],
  };
}

const CORE_IDEAS = [
  'Make sure the pain is real before you build',
  "B2B demand doesn't prove B2C demand",
  "Don't make OAuth integrations your core value",
];

function ideaOf(id: string, coreIdea: string, postingOrder: number, wholeBrief = false) {
  return {
    id,
    postingOrder,
    wholeBrief,
    plan: {
      coreIdea,
      takeaway: 'Ship it.',
      funnel: 'middle' as const,
      desiredAction: 'bookmark' as const,
      format: 'post' as const,
      length: 'short' as const,
      structure: 'few_lines',
    },
    post: null,
  };
}

/** What planning a Brief of three separate ideas answers: its Ideas, nothing written yet. */
const SPLIT: Brief = {
  id: 'brief_02',
  text: 'three things I learned from my failed SaaS',
  createdAt: '2026-10-10T12:00:30Z',
  ideas: [
    ideaOf('idea_whole', 'Three lessons from a failed SaaS', 1, true),
    ...CORE_IDEAS.map((coreIdea, index) => ideaOf(`idea_${index + 1}`, coreIdea, index + 1)),
  ],
  generationsLeft: 382,
};

/** The Brief as writing `ideaIds` answers it, each one's Post being written. */
function writing(brief: Brief, ideaIds: string[]): Brief {
  return {
    ...brief,
    ideas: brief.ideas.map((idea) =>
      ideaIds.includes(idea.id)
        ? {
            ...idea,
            post: {
              id: `post_${idea.id}`,
              writingState: 'writing',
              status: null,
              publishing: false,
              text: null,
              textMedia: [],
            },
          }
        : idea,
    ),
  };
}

/** What planning a Brief of one idea answers: its Post, its first Version being written. */
const STARTED: Brief = {
  id: 'brief_01',
  text: 'ship small things',
  createdAt: '2026-10-10T12:00:30Z',
  ideas: [
    {
      id: 'idea_01',
      postingOrder: 1,
      wholeBrief: true,
      plan: null,
      post: {
        id: 'post_01',
        writingState: 'writing',
        status: null,
        publishing: false,
        text: null,
        textMedia: [],
      },
    },
  ],
  generationsLeft: 381,
};

/** A Brief of one idea planned when there was no room to write it: its Post isn't started. */
function unwritten(generationsLeft: number): Brief {
  return {
    id: 'brief_03',
    text: 'ship small things',
    createdAt: '2026-10-10T12:00:30Z',
    ideas: [ideaOf('idea_only', 'Ship small things, often', 1, true)],
    generationsLeft,
  };
}

async function readyToWrite() {
  vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
  renderNewPost();
  const area = await writer();
  await area.findByRole('button', { name: 'Plan posts' });
  return area;
}

async function writeBrief(area: Awaited<ReturnType<typeof writer>>, brief: string) {
  fireEvent.change(area.getByLabelText('Brief'), { target: { value: brief } });
  fireEvent.click(area.getByRole('button', { name: 'Plan posts' }));
}

/** Make billing offer a €10 Top-up, behind Terms of `termsVersion`, for this test only. */
function sellingTopUps(termsVersion: string | null) {
  const fetchPlans = vi.mocked(billingService.fetchPlans);
  const before = fetchPlans.getMockImplementation();
  fetchPlans.mockResolvedValue({
    plans: [],
    termsVersion,
    couponsEnabled: false,
    allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
    trial: null,
    topUp: { amount: 1000, currency: 'eur', generations: 250, xPosts: 50, linkXPosts: 5 },
  });
  onTestFinished(() => {
    fetchPlans.mockImplementation(before ?? (() => Promise.reject(new Error('unmocked'))));
  });
}

describe('New post', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(NOT_SUBSCRIBED);
    vi.mocked(briefService.plan).mockReset();
    vi.mocked(positioningService.get)
      .mockReset()
      .mockResolvedValue({ text: 'I post about bootstrapping.', canDraft: true });
    vi.mocked(postService.get).mockReset().mockResolvedValue(postWith('the final text'));
    vi.mocked(postService.addVersion).mockReset();
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
    vi.mocked(usageService.get).mockReset().mockResolvedValue({ allowance: null });
    vi.mocked(track).mockClear();
  });

  it('shows one line above the composer, with no instructions or field labels', async () => {
    renderNewPost();

    expect(await screen.findByRole('heading', { level: 1, name: 'New post' })).toBeInTheDocument();
    const area = await writer();
    expect(area.getByRole('heading', { level: 2, name: "What's the post about?" })).toBeVisible();
    const brief = area.getByLabelText('Brief');
    expect(brief).toHaveAttribute('placeholder', 'Write a new post about…');
    expect(brief).toHaveFocus();
    expect(area.queryByRole('radiogroup', { name: 'Format' })).not.toBeInTheDocument();
    expect(area.queryByText('Brief')).not.toBeInTheDocument();
    expect(area.queryByText('Format')).not.toBeInTheDocument();
    expect(area.queryByText(/rambling is fine/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'How your posts sound' })).not.toBeInTheDocument();
  });

  it('takes the Brief in words only, with no way to attach media', async () => {
    const area = await readyToWrite();

    expect(area.queryByRole('button', { name: /media/i })).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  describe('Persona link', () => {
    it('links to the Persona page from the header, naming no author', async () => {
      vi.mocked(inspirationAuthorService.list).mockResolvedValue([LEVELSIO, PAULG]);
      renderNewPost();

      const heading = await screen.findByRole('heading', { level: 1, name: 'New post' });
      const header = within(heading.closest('header')!);
      const link = await header.findByRole('link', { name: 'Persona' });
      expect(link).toHaveAttribute('href', '/persona');
      expect(link).toHaveTextContent(/^Persona$/);
      expect(link.querySelector('img')).toBeNull();
      expect(inspirationAuthorService.list).not.toHaveBeenCalled();

      fireEvent.click(link);

      expect(await screen.findByRole('heading', { level: 1, name: 'Persona' })).toBeInTheDocument();
    });
  });

  describe('Writing a Post', () => {
    it('writes a single post for a User with a Positioning and no Inspiration authors', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      renderNewPost();

      const area = await writer();
      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'ship small things' } });

      await waitFor(() => expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled());
      expect(area.queryByRole('link', { name: 'Set up your persona' })).not.toBeInTheDocument();
    });

    it('lets a User with no Inspiration author write, since the planner chooses a single post or a thread', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(briefService.plan).mockResolvedValue(STARTED);
      renderNewPost();

      const area = await writer();
      expect(area.queryByRole('radiogroup', { name: 'Format' })).not.toBeInTheDocument();
      expect(area.queryByRole('radio', { name: 'Thread' })).not.toBeInTheDocument();
      fireEvent.change(area.getByLabelText('Brief'), {
        target: { value: 'five lessons from shipping weekly, as a thread' },
      });
      await waitFor(() => expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled());
      fireEvent.click(area.getByRole('button', { name: 'Plan posts' }));

      expect(briefService.plan).toHaveBeenCalledWith(
        'five lessons from shipping weekly, as a thread',
      );
      expect(area.queryByRole('link', { name: 'Set up your persona' })).not.toBeInTheDocument();
    });

    it('replaces the write button with "Set up your persona" while the User has no Positioning', async () => {
      vi.mocked(billingService.fetchBillingMe).mockResolvedValue(SUBSCRIBED);
      vi.mocked(positioningService.get).mockResolvedValue({ text: null, canDraft: true });
      renderNewPost();

      const area = await writer();
      const setUp = await area.findByRole('link', { name: 'Set up your persona' });
      expect(setUp).toHaveAttribute('href', '/persona');
      expect(area.queryByRole('button', { name: 'Plan posts' })).not.toBeInTheDocument();
    });

    it('keeps the write button when the Positioning could not be read, so the refusal can say why', async () => {
      vi.mocked(positioningService.get).mockRejectedValue(apiError(500, 'The server is down.'));
      const area = await readyToWrite();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'ship small things' } });

      await waitFor(() => expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled());
      expect(area.queryByRole('link', { name: 'Set up your persona' })).not.toBeInTheDocument();
    });

    it('greys out the send arrow until something is typed', async () => {
      const area = await readyToWrite();
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeDisabled();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: '   ' } });
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeDisabled();

      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'ship small things' } });
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled();
    });

    it.each([
      ['⌘Enter', { metaKey: true }],
      ['Ctrl+Enter', { ctrlKey: true }],
    ])('sends the Brief with %s', async (_, modifier) => {
      vi.mocked(briefService.plan).mockReturnValue(new Promise(() => {}));
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'ship small things' } });

      fireEvent.keyDown(brief, { key: 'Enter', ...modifier });

      expect(briefService.plan).toHaveBeenCalledWith('ship small things');
    });

    it('leaves Enter alone, so it adds a newline instead of sending', async () => {
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');
      fireEvent.change(brief, { target: { value: 'ship small things' } });

      const enter = fireEvent.keyDown(brief, { key: 'Enter' });

      expect(enter).toBe(true);
      expect(briefService.plan).not.toHaveBeenCalled();
    });

    it("plans the Brief, locking the composer while it waits, then opens the Post's page", async () => {
      let answer: (brief: Brief) => void = () => {};
      vi.mocked(briefService.plan).mockReturnValue(new Promise((resolve) => (answer = resolve)));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(area.getByLabelText('Brief')).toBeDisabled();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(area.getByRole('button', { name: 'Reading your brief…' })).toBeDisabled();
      expect(area.getByRole('status')).toHaveTextContent('Reading your brief…');
      expect(briefService.plan).toHaveBeenCalledWith('ship small things');
      expect(track).not.toHaveBeenCalledWith('post_version_requested', expect.anything());

      answer(STARTED);

      await waitFor(() =>
        expect(screen.getByRole('status', { name: 'Current path' })).toHaveTextContent(
          '/posts/post_01',
        ),
      );
      const card = within(await screen.findByRole('article', { name: 'Text' }));
      expect(card.getByText('the final text')).toBeInTheDocument();
      expect(postService.get).toHaveBeenCalledWith('post_01');
      expect(vi.mocked(track).mock.calls.filter(([e]) => e === 'post_version_requested')).toEqual([
        ['post_version_requested', { kind: 'brief' }],
      ]);
    });

    it('empties the form on New post', async () => {
      const area = await readyToWrite();
      fireEvent.change(area.getByLabelText('Brief'), { target: { value: 'half a thought' } });

      fireEvent.click(
        within(screen.getAllByRole('navigation', { name: 'Main' })[0]!).getByRole('link', {
          name: 'New post',
        }),
      );

      const fresh = await writer();
      await waitFor(() => expect(fresh.getByLabelText('Brief')).toHaveValue(''));
      expect(fresh.getByLabelText('Brief')).toHaveFocus();
    });

    it('shows a failure, keeps the Brief and retries it as a new Post', async () => {
      vi.mocked(briefService.plan)
        .mockRejectedValueOnce(apiError(502, 'Writing the post failed. Please try again.'))
        .mockResolvedValueOnce(STARTED);
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      const alert = await area.findByRole('alert');
      expect(alert).toHaveTextContent('Writing the post failed. Please try again.');
      expect(
        area.getByLabelText('Brief').compareDocumentPosition(alert) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(track).toHaveBeenCalledWith('brief_plan_failed');
      expect(track).not.toHaveBeenCalledWith('post_version_failed', expect.anything());

      fireEvent.click(area.getByRole('button', { name: 'Try again' }));

      expect(await screen.findByRole('article', { name: 'Text' })).toBeInTheDocument();
      expect(briefService.plan).toHaveBeenCalledTimes(2);
      expect(briefService.plan).toHaveBeenNthCalledWith(2, 'ship small things');
    });

    it('says when the User can write again once they reach the hourly limit', async () => {
      vi.mocked(briefService.plan).mockRejectedValue(
        apiError(429, "You've made 30 attempts at a version in the last hour.", {
          retry_at: new Date(2026, 9, 6, 15, 42).toISOString(),
        }),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(
        await area.findByText(
          "You've made 30 attempts at a version in the last hour. You can write again at 3:42 PM.",
        ),
      ).toHaveAttribute('role', 'status');
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
    });

    it('shows the Allowance refusal in place of the error banner', async () => {
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
        ),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(
        await area.findByText(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
        ),
      ).toBeInTheDocument();
      expect(area.queryByRole('alert')).not.toBeInTheDocument();
      expect(area.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
      expect(area.getByLabelText('Brief')).toHaveValue('ship small things');
      expect(track).toHaveBeenCalledWith('allowance_used_up', { ran_out: 'generations' });
      expect(track).not.toHaveBeenCalledWith('brief_plan_failed');
    });

    it('says how many generations are left once less than 10% is left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({ generations: { limit: 500, used: 457, left: 43 } }),
      );
      const area = await readyToWrite();

      expect(await area.findByText('43 generations left until 14 November')).toBeInTheDocument();
    });

    it('says nothing about generations while 10% or more is left', async () => {
      vi.mocked(usageService.get).mockResolvedValue(
        usageWith({ generations: { limit: 500, used: 450, left: 50 } }),
      );
      const area = await readyToWrite();
      await waitFor(() => expect(usageService.get).toHaveBeenCalled());

      expect(area.queryByText(/generations left/)).not.toBeInTheDocument();
    });

    it('offers to update the payment method to a User behind on payment at the limit', async () => {
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
          { way_out: 'update_payment' },
        ),
      );
      vi.mocked(billingService.openBillingPortal).mockResolvedValue('https://billing.test/portal');
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');
      fireEvent.click(await area.findByRole('button', { name: 'Update your payment method' }));

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://billing.test/portal'));
    });

    it('offers a paid-up User at the limit to buy a top-up, behind the Terms', async () => {
      sellingTopUps('2026-10-11');
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp(
          "You've used this period's 500 generations. They reset on 14 November. Failed attempts don't count.",
          { way_out: 'top_up' },
        ),
      );
      vi.mocked(billingService.startTopUpCheckout).mockResolvedValue('https://checkout.test/t');
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');
      fireEvent.click(await area.findByRole('button', { name: 'Buy top-up, €10' }));

      const dialog = await screen.findByRole('dialog', { name: 'Buy a top-up' });
      expect(
        within(dialog).getByText(
          '250 generations and 50 X posts, up to 5 with a link, for €10. Lasts 12 months, used after your monthly allowance.',
        ),
      ).toBeInTheDocument();
      expect(
        within(dialog).getByRole('checkbox', {
          name: 'I ask for the top-up to be available immediately, and acknowledge I lose the 14-day right of withdrawal once I use any of it.',
        }),
      ).toBeInTheDocument();
      const pay = within(dialog).getByRole('button', { name: 'Pay €10' });
      expect(pay).toBeDisabled();
      for (const box of within(dialog).getAllByRole('checkbox')) fireEvent.click(box);
      fireEvent.click(pay);

      await waitFor(() => expect(redirectTo).toHaveBeenCalledWith('https://checkout.test/t'));
      expect(billingService.startTopUpCheckout).toHaveBeenCalledWith('2026-10-11', {
        acceptedTerms: true,
        requestedImmediateStart: true,
        approvedSpecificClauses: true,
      });
      expect(track).toHaveBeenCalledWith('top_up_checkout_started');
    });

    it("shows the API's refusal of a top-up checkout in the dialog", async () => {
      sellingTopUps(null);
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp("You've used this period's 500 generations.", { way_out: 'top_up' }),
      );
      vi.mocked(billingService.startTopUpCheckout).mockRejectedValue(
        apiError(409, 'Update your payment method to buy a top-up.'),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');
      fireEvent.click(await area.findByRole('button', { name: 'Buy top-up, €10' }));
      const dialog = await screen.findByRole('dialog', { name: 'Buy a top-up' });
      fireEvent.click(within(dialog).getByRole('button', { name: 'Pay €10' }));

      expect(await within(dialog).findByRole('alert')).toHaveTextContent(
        'Update your payment method to buy a top-up.',
      );
    });

    it('offers a trial User at the limit to subscribe now, and subscribes', async () => {
      const noPlans = await billingService.fetchPlans();
      onTestFinished(() => void vi.mocked(billingService.fetchPlans).mockResolvedValue(noPlans));
      vi.mocked(billingService.fetchPlans).mockResolvedValue({
        plans: [
          {
            key: 'pumpkit_pro_monthly',
            productName: 'Pro',
            amount: 1900,
            currency: 'eur',
            interval: 'month',
            intervalCount: 1,
          },
        ],
        couponsEnabled: false,
        termsVersion: '2026-10-11',
        allowance: { generations: 500, xPosts: 100, linkXPosts: 10 },
        trial: null,
        topUp: null,
      });
      vi.mocked(billingService.subscribeNow).mockResolvedValue(SUBSCRIBED);
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp(
          "You've used your trial's 125 generations. Your trial ends on 14 November. Failed attempts don't count.",
          { way_out: 'subscribe_now' },
        ),
      );
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');
      fireEvent.click(await area.findByRole('button', { name: 'Subscribe now' }));
      const dialog = within(await screen.findByRole('dialog'));
      expect(
        await dialog.findByText(
          "Your trial ends now and you're charged €19.00 today for your first month. Your monthly allowance of 500 generations and 100 X posts starts at once.",
        ),
      ).toBeInTheDocument();
      fireEvent.click(dialog.getByRole('button', { name: 'Subscribe now' }));

      expect(
        await screen.findByText('Subscribed. Your monthly allowance has started.'),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(screen.queryByText(/You've used your trial's/)).not.toBeInTheDocument(),
      );
    });

    it('asks for billing once when the subscribe now dialog fails to load it', async () => {
      vi.mocked(briefService.plan).mockRejectedValue(
        allowanceUsedUp("You've used your trial's 125 generations.", {
          way_out: 'subscribe_now',
        }),
      );
      const area = await readyToWrite();
      await writeBrief(area, 'ship small things');
      const subscribeNow = await area.findByRole('button', { name: 'Subscribe now' });
      const fetchPlans = vi.mocked(billingService.fetchPlans);
      const before = fetchPlans.getMockImplementation();
      onTestFinished(() => void fetchPlans.mockImplementation(before!));
      // Billing answers only on a second ask, which the dialog must not make.
      fetchPlans.mockRejectedValueOnce(new Error('down'));

      fireEvent.click(subscribeNow);

      const dialog = within(await screen.findByRole('dialog'));
      const failed = "Couldn't load billing information. Reload the page to try again.";
      expect(await dialog.findByText(failed)).toBeInTheDocument();
      for (let i = 0; i < 5; i++) await act(() => Promise.resolve());
      expect(dialog.getByText(failed)).toBeInTheDocument();
    });

    it.each([
      [403, 'This needs a subscription. Subscribe to continue.'],
      [422, 'The Brief is too long.'],
      [429, "You've made 30 attempts at a version in the last hour."],
    ])('does not count a refusal with a %i as a failed plan', async (status, detail) => {
      vi.mocked(briefService.plan).mockRejectedValue(apiError(status, detail));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      await waitFor(() => expect(briefService.plan).toHaveBeenCalled());
      await waitFor(() => expect(area.getByLabelText('Brief')).toBeEnabled());
      expect(track).not.toHaveBeenCalledWith('brief_plan_failed');
    });

    it('counts a failure without a response as a failed plan', async () => {
      vi.mocked(briefService.plan).mockRejectedValue(new Error('Network Error'));
      const area = await readyToWrite();

      await writeBrief(area, 'ship small things');

      expect(await area.findByRole('alert')).toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('brief_plan_failed');
    });

    it('shows a length counter only near the Brief limit, and refuses a Brief over it', async () => {
      const area = await readyToWrite();
      const brief = area.getByLabelText('Brief');

      fireEvent.change(brief, { target: { value: 'a'.repeat(1000) } });
      expect(area.queryByText(/200,000/)).not.toBeInTheDocument();

      fireEvent.change(brief, { target: { value: 'a'.repeat(195_000) } });
      expect(area.getByText('195,000 / 200,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled();

      fireEvent.change(brief, { target: { value: 'a'.repeat(200_005) } });
      expect(area.getByText('5 characters over the 200,000 limit')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeDisabled();
    });

    it('counts an emoji in the Brief as one character, as the backend does', async () => {
      const area = await readyToWrite();

      fireEvent.change(area.getByLabelText('Brief'), {
        target: { value: 'a'.repeat(199_999) + '😀' },
      });

      expect(area.getByText('200,000 / 200,000 characters')).toBeInTheDocument();
      expect(area.getByRole('button', { name: 'Plan posts' })).toBeEnabled();
    });
  });

  describe('Ideas step', () => {
    async function ideasStep(planned: Brief = SPLIT) {
      vi.mocked(briefService.plan).mockResolvedValue(planned);
      const area = await readyToWrite();
      await writeBrief(area, planned.text);
      return within(await screen.findByRole('region', { name: 'We found 3 ideas in your brief' }));
    }

    beforeEach(() => {
      vi.mocked(briefService.write).mockReset();
      vi.mocked(usageService.get).mockResolvedValue(usageWith());
    });

    it('lists the ideas as a numbered checklist in posting order, all ticked', async () => {
      const step = await ideasStep();

      const boxes = step.getAllByRole('checkbox');
      expect(boxes.map((box) => box.closest('label')?.textContent)).toEqual(
        CORE_IDEAS.map((coreIdea, index) => `${index + 1}${coreIdea}`),
      );
      expect(boxes.every((box) => (box as HTMLInputElement).checked)).toBe(true);
      expect(step.getByRole('radio', { name: 'One post per idea' })).toBeChecked();
      expect(await step.findByText('3 generations · 382 left')).toBeInTheDocument();
      expect(step.getByRole('button', { name: 'Write 3 posts' })).toBeEnabled();
      expect(screen.queryByLabelText('Brief')).not.toBeInTheDocument();
      expect(track).toHaveBeenCalledWith('brief_planned', { split_ideas: 3 });
      expect(track).not.toHaveBeenCalledWith('post_version_requested', expect.anything());
    });

    it('writes only the ticked ideas and opens the brief page', async () => {
      vi.mocked(briefService.write).mockResolvedValue(writing(SPLIT, ['idea_1', 'idea_3']));
      vi.mocked(briefService.get).mockResolvedValue(writing(SPLIT, ['idea_1', 'idea_3']));
      const step = await ideasStep();

      fireEvent.click(step.getByRole('checkbox', { name: /B2B/ }));
      expect(await step.findByText('2 generations · 382 left')).toBeInTheDocument();
      fireEvent.click(step.getByRole('button', { name: 'Write 2 posts' }));

      expect(briefService.write).toHaveBeenCalledWith('brief_02', ['idea_1', 'idea_3']);
      await waitFor(() => expect(currentPath()).toBe('/briefs/brief_02'));
      expect(track).toHaveBeenCalledWith('ideas_write_requested', { count: 2, choice: 'each' });
      expect(vi.mocked(track).mock.calls.filter(([e]) => e === 'post_version_requested')).toEqual([
        ['post_version_requested', { kind: 'brief' }],
        ['post_version_requested', { kind: 'brief' }],
      ]);
    });

    it('writes one post covering everything, greying the list, and opens that post', async () => {
      vi.mocked(briefService.write).mockResolvedValue(writing(SPLIT, ['idea_whole']));
      const step = await ideasStep();

      fireEvent.click(step.getByRole('radio', { name: 'One post covering everything' }));

      for (const box of step.getAllByRole('checkbox')) expect(box).toBeDisabled();
      expect(step.getByText(/^1 generation · /)).toBeInTheDocument();
      fireEvent.click(step.getByRole('button', { name: 'Write 1 post' }));

      expect(briefService.write).toHaveBeenCalledWith('brief_02', ['idea_whole']);
      await waitFor(() => expect(currentPath()).toBe('/posts/post_idea_whole'));
    });

    it('disables the button while nothing is ticked', async () => {
      const step = await ideasStep();

      for (const box of step.getAllByRole('checkbox')) fireEvent.click(box);

      expect(step.getByRole('button', { name: 'Write 0 posts' })).toBeDisabled();
    });

    it('counts the generations left as the server does, writes in progress taken out', async () => {
      const step = await ideasStep({ ...SPLIT, generationsLeft: 2 });

      expect(await step.findByText(/3 generations · 2 left/)).toBeInTheDocument();
      expect(step.getByRole('button', { name: 'Write 3 posts' })).toBeDisabled();
    });

    it('with too few generations shows how many are left with a top-up link, until the ticks fit', async () => {
      vi.mocked(usageService.get).mockResolvedValue(usageWith({ mayBuyTopUp: true }));
      const step = await ideasStep({ ...SPLIT, generationsLeft: 1 });

      expect(await step.findByText(/3 generations · 1 left/)).toBeInTheDocument();
      expect(step.getByRole('link', { name: 'Top up' })).toHaveAttribute('href', '/settings');
      expect(step.getByRole('button', { name: 'Write 3 posts' })).toBeDisabled();

      fireEvent.click(step.getAllByRole('checkbox')[0]!);
      fireEvent.click(step.getAllByRole('checkbox')[1]!);

      expect(step.getByText('1 generation · 1 left')).toBeInTheDocument();
      expect(step.queryByRole('link', { name: 'Top up' })).not.toBeInTheDocument();
      expect(step.getByRole('button', { name: 'Write 1 post' })).toBeEnabled();
    });

    it('shows a failure to start inline and keeps the ticks', async () => {
      vi.mocked(briefService.write).mockRejectedValue(
        apiError(502, 'Writing the posts failed. Please try again.'),
      );
      const step = await ideasStep();
      fireEvent.click(step.getAllByRole('checkbox')[1]!);

      fireEvent.click(step.getByRole('button', { name: 'Write 2 posts' }));

      expect(await step.findByRole('alert')).toHaveTextContent(
        'Writing the posts failed. Please try again.',
      );
      expect(track).toHaveBeenCalledWith('ideas_write_failed');
      expect(track).not.toHaveBeenCalledWith('post_version_requested', expect.anything());
      expect(step.getAllByRole('checkbox').map((box) => (box as HTMLInputElement).checked)).toEqual(
        [true, false, true],
      );
      expect(currentPath()).toBe('/new');
    });

    it('does not count a refused write as a failed one', async () => {
      vi.mocked(briefService.write).mockRejectedValue(
        apiError(422, 'Write one post covering everything, or one post per idea, not both.'),
      );
      const step = await ideasStep();

      fireEvent.click(step.getByRole('button', { name: 'Write 3 posts' }));

      expect(await step.findByRole('alert')).toHaveTextContent(
        'Write one post covering everything, or one post per idea, not both.',
      );
      expect(track).not.toHaveBeenCalledWith('ideas_write_failed');
    });

    it('opens the brief page when the ideas turn out to be written already', async () => {
      vi.mocked(briefService.write).mockRejectedValue(
        apiError(409, 'One of these ideas is already written.', {
          code: 'IDEAS_ALREADY_WRITTEN',
        }),
      );
      vi.mocked(briefService.get).mockResolvedValue(writing(SPLIT, ['idea_1', 'idea_2', 'idea_3']));
      const step = await ideasStep();

      fireEvent.click(step.getByRole('button', { name: 'Write 3 posts' }));

      await waitFor(() => expect(currentPath()).toBe('/briefs/brief_02'));
    });

    it('goes back to the composer with the brief kept on "Edit brief"', async () => {
      const step = await ideasStep();

      fireEvent.click(step.getByRole('button', { name: 'Edit brief' }));

      const area = await writer();
      expect(area.getByLabelText('Brief')).toHaveValue(SPLIT.text);
      expect(briefService.write).not.toHaveBeenCalled();
    });
  });

  describe('A brief of one idea planned with no room to write it', () => {
    async function planned(brief: Brief) {
      vi.mocked(briefService.plan).mockResolvedValue(brief);
      const area = await readyToWrite();
      await writeBrief(area, brief.text);
      return within(
        await screen.findByRole('region', { name: 'We planned one post from your brief' }),
      );
    }

    beforeEach(() => {
      vi.mocked(briefService.write).mockReset();
      vi.mocked(usageService.get).mockResolvedValue(usageWith({ mayBuyTopUp: true }));
    });

    it('shows its idea with no generation left and a top-up link, and writes nothing', async () => {
      const step = await planned(unwritten(0));

      expect(step.getByText('Ship small things, often')).toBeInTheDocument();
      expect(step.queryByRole('checkbox')).not.toBeInTheDocument();
      expect(step.queryByRole('radiogroup')).not.toBeInTheDocument();
      expect(await step.findByText(/1 generation · 0 left/)).toBeInTheDocument();
      expect(step.getByRole('link', { name: 'Top up' })).toHaveAttribute('href', '/settings');
      expect(step.getByRole('button', { name: 'Write 1 post' })).toBeDisabled();
      expect(currentPath()).toBe('/new');
      expect(track).not.toHaveBeenCalledWith('post_version_requested', expect.anything());
    });

    it('writes it once there is room', async () => {
      vi.mocked(briefService.write).mockResolvedValue({
        ...unwritten(4),
        ideas: [
          {
            ...ideaOf('idea_only', 'Ship small things, often', 1, true),
            post: {
              id: 'post_only',
              writingState: 'writing',
              status: null,
              publishing: false,
              text: null,
              textMedia: [],
            },
          },
        ],
      });
      const step = await planned(unwritten(5));

      fireEvent.click(step.getByRole('button', { name: 'Write 1 post' }));

      expect(briefService.write).toHaveBeenCalledWith('brief_03', ['idea_only']);
      await waitFor(() => expect(currentPath()).toBe('/posts/post_only'));
    });
  });

  describe('On an Instance that sells no Plans', () => {
    const NO_PLANS: Instance = { ...SELLS_PLANS, sells_plans: false };

    it('lets a User without a Subscription write, with no prompt to subscribe', async () => {
      renderNewPost(undefined, NO_PLANS);

      const area = await writer();
      expect(await area.findByRole('button', { name: 'Plan posts' })).toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /subscribe/i })).not.toBeInTheDocument();
      expect(billingService.fetchBillingMe).not.toHaveBeenCalled();
    });
  });
});

function recentBrief(changes: Partial<RecentBrief>): RecentBrief {
  return {
    id: 'brief_recent',
    textStart: 'so I have been testing something this week…',
    postsWritten: 0,
    postsWriting: 0,
    postsNotWritten: 0,
    ideasOffered: 0,
    postIds: [],
    ...changes,
  };
}

const PARTLY_WRITTEN = recentBrief({
  id: 'brief_partly',
  textStart: 'so I have been testing something this week…',
  postsWritten: 3,
  ideasOffered: 1,
  postIds: ['post_a', 'post_b', 'post_c'],
});
const WRITING = recentBrief({
  id: 'brief_writing',
  textStart: 'two separate things I learned this month…',
  postsWritten: 1,
  postsWriting: 1,
  postIds: ['post_d', 'post_e'],
});
const ALL_WRITTEN = recentBrief({
  id: 'brief_all',
  textStart: 'I want to write about my SaaS failures…',
  postsWritten: 5,
  postIds: ['post_f', 'post_g', 'post_h', 'post_i', 'post_j'],
});
const ONE_POST = recentBrief({
  id: 'brief_one',
  textStart: 'ship small things',
  postsWritten: 1,
  postIds: ['post_only'],
});
const NOT_WRITTEN_YET = recentBrief({
  id: 'brief_unwritten',
  textStart: 'a brief planned with no room left',
  ideasOffered: 1,
});
const COULD_NOT_WRITE = recentBrief({
  id: 'brief_failed',
  textStart: 'three things about pricing',
  postsWritten: 1,
  postsNotWritten: 1,
  postIds: ['post_k', 'post_l'],
});

async function recentBriefs() {
  return within(await screen.findByRole('region', { name: 'Recent briefs' }));
}

describe('Recent briefs on New post', () => {
  beforeEach(() => {
    vi.mocked(billingService.fetchBillingMe).mockReset().mockResolvedValue(SUBSCRIBED);
    vi.mocked(briefService.recent).mockReset().mockResolvedValue([]);
    vi.mocked(positioningService.get)
      .mockReset()
      .mockResolvedValue({ text: 'I post about bootstrapping.', canDraft: true });
    vi.mocked(usageService.get).mockReset().mockResolvedValue({ allowance: null });
    vi.mocked(xConnectionService.get).mockReset().mockResolvedValue(null);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('is not shown when the user has no briefs', async () => {
    renderNewPost();
    await writer();
    await waitFor(() => expect(briefService.recent).toHaveBeenCalled());

    expect(screen.queryByRole('region', { name: 'Recent briefs' })).not.toBeInTheDocument();
  });

  it('lists each brief by its start with its progress', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([
      PARTLY_WRITTEN,
      ALL_WRITTEN,
      NOT_WRITTEN_YET,
      COULD_NOT_WRITE,
    ]);
    renderNewPost();

    const list = await recentBriefs();
    expect(list.getByRole('heading', { level: 2, name: 'Recent briefs' })).toBeVisible();
    const rows = list.getAllByRole('link');
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveAccessibleName(
      'so I have been testing something this week…, 3 of 4 written',
    );
    expect(rows[1]).toHaveAccessibleName('I want to write about my SaaS failures…, 5 written');
    expect(rows[2]).toHaveAccessibleName('a brief planned with no room left, Not written yet');
    expect(rows[3]).toHaveAccessibleName("three things about pricing, 1 post couldn't be written");
  });

  it('shows a brief with a post being written as writing', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([WRITING]);
    renderNewPost();

    const list = await recentBriefs();
    expect(
      list.getByRole('link', { name: 'two separate things I learned this month…, Writing…' }),
    ).toBeVisible();
  });

  it('opens the brief page from a brief with several posts', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([PARTLY_WRITTEN]);
    vi.mocked(briefService.get).mockReturnValue(new Promise(() => {}));
    renderNewPost();

    fireEvent.click((await recentBriefs()).getByRole('link', { name: /so I have been testing/ }));

    await waitFor(() => expect(currentPath()).toBe('/briefs/brief_partly'));
  });

  it('opens the post from a brief with one post and no idea left to write', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([ONE_POST]);
    renderNewPost();

    fireEvent.click((await recentBriefs()).getByRole('link', { name: /ship small things/ }));

    await waitFor(() => expect(currentPath()).toBe('/posts/post_only'));
  });

  it('opens the brief page from a brief not written yet, to write its ideas', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([NOT_WRITTEN_YET]);
    vi.mocked(briefService.get).mockReturnValue(new Promise(() => {}));
    renderNewPost();

    fireEvent.click((await recentBriefs()).getByRole('link', { name: /no room left/ }));

    await waitFor(() => expect(currentPath()).toBe('/briefs/brief_unwritten'));
  });

  it('reads the list again while a brief is writing, and stops once none is', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(briefService.recent)
      .mockResolvedValueOnce([WRITING])
      .mockResolvedValue([{ ...WRITING, postsWritten: 2, postsWriting: 0 }]);
    renderNewPost();
    await recentBriefs();
    expect(briefService.recent).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECENT_BRIEFS_POLL_MS);
    });

    const list = await recentBriefs();
    expect(await list.findByRole('link', { name: /2 written/ })).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECENT_BRIEFS_POLL_MS * 3);
    });
    expect(briefService.recent).toHaveBeenCalledTimes(2);
  });

  it('does not read the list again while no brief is writing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(briefService.recent).mockResolvedValue([ALL_WRITTEN]);
    renderNewPost();
    await recentBriefs();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(RECENT_BRIEFS_POLL_MS * 3);
    });

    expect(briefService.recent).toHaveBeenCalledTimes(1);
  });

  it('gives way to the ideas step while the user picks ideas', async () => {
    vi.mocked(briefService.recent).mockResolvedValue([ALL_WRITTEN]);
    vi.mocked(briefService.plan).mockResolvedValue(SPLIT);
    renderNewPost();
    await recentBriefs();

    await writeBrief(await writer(), 'three things I learned from my failed SaaS');

    expect(await screen.findByText('We found 3 ideas in your brief')).toBeVisible();
    expect(screen.queryByRole('region', { name: 'Recent briefs' })).not.toBeInTheDocument();
  });
});
