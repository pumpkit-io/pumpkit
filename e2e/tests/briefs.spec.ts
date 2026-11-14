import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

// The stack's model is real and costs money, so POST /briefs and POST /briefs/{id}/posts are
// answered here: the seed stores the Brief and its Posts, and GET /briefs/{id} reads them back.
// The backend suite covers both POSTs (tests/posts/test_writing_the_ideas_of_a_brief.py).
let briefId = '';

test.beforeEach(() => {
  const out = runSeedScript('planned_brief.py', ['plan']);
  briefId = out.match(/BRIEF_ID=(\S+)/)?.[1] ?? '';
  if (!briefId) throw new Error(`Seed script did not print a brief id. Output:\n${out}`);
});

test.afterEach(() => {
  runSeedScript('planned_brief.py', ['clean']);
});

test('a brief of several ideas is written as the ideas picked, which fill in on its page', async ({
  page,
}) => {
  await page.route('**/api/v1/briefs', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    const read = await route.fetch({
      url: route
        .request()
        .url()
        .replace(/\/briefs$/, `/briefs/${briefId}`),
      method: 'GET',
    });
    await route.fulfill({ response: read, status: 201 });
  });
  let picked: string[] = [];
  await page.route(`**/api/v1/briefs/${briefId}/posts`, async (route) => {
    picked = (route.request().postDataJSON() as { idea_ids: string[] }).idea_ids;
    runSeedScript('planned_brief.py', ['writing', briefId, ...picked]);
    const read = await route.fetch({
      url: route
        .request()
        .url()
        .replace(/\/posts$/, ''),
      method: 'GET',
    });
    await route.fulfill({ response: read, status: 202 });
  });
  await page.goto('/new');

  await page.getByLabel('Brief').fill('Three things my failed SaaS taught me.');
  await page.getByRole('button', { name: 'Plan posts' }).click();

  const step = page.getByRole('region', { name: 'We found 3 ideas in your brief' });
  await expect(step.getByRole('checkbox')).toHaveCount(3);
  await step.getByRole('checkbox', { name: /Charge at least 20 euros/ }).uncheck();
  await step.getByRole('button', { name: 'Write 2 posts' }).click();

  await expect(page).toHaveURL(new RegExp(`/briefs/${briefId}$`));
  expect(picked).toHaveLength(2);
  const cards = page.getByRole('main').getByRole('listitem');
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toHaveAttribute(
    'aria-label',
    'Make sure the pain is real before you build',
  );
  await expect(cards.nth(1)).toHaveAttribute(
    'aria-label',
    "Don't make OAuth integrations your core value",
  );
  await expect(page.getByText('Writing…')).toHaveCount(2);

  runSeedScript('planned_brief.py', ['written', briefId]);

  await expect(
    cards.nth(0).getByText('Written: Make sure the pain is real before you build.'),
  ).toBeVisible();
  await expect(
    cards.nth(1).getByText("Written: Don't make OAuth integrations your core value."),
  ).toBeVisible();
  await expect(page.getByText('Writing…')).toHaveCount(0);
  await cards.nth(0).getByRole('link', { name: /^Open/ }).click();
  await expect(page).toHaveURL(/\/posts\/post_/);
});
