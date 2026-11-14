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

test('a brief of several ideas is written as the ideas picked, which fill in on its page, and one left is written later', async ({
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

  await page.getByRole('textbox', { name: 'Brief' }).fill('Three things my failed SaaS taught me.');
  await page.getByRole('button', { name: 'Plan posts' }).click();

  const step = page.getByRole('region', { name: 'We found 3 ideas in your brief' });
  await expect(step.getByRole('checkbox')).toHaveCount(3);
  await step.getByRole('checkbox', { name: /Charge at least 20 euros/ }).uncheck();
  await step.getByRole('button', { name: 'Write 2 posts' }).click();

  await expect(page).toHaveURL(new RegExp(`/briefs/${briefId}$`));
  expect(picked).toHaveLength(2);
  const cards = page.getByRole('list', { name: 'Posts' }).getByRole('listitem');
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
  await expect(page.getByText('2 of 3 written')).toBeVisible();

  runSeedScript('planned_brief.py', ['written', briefId]);

  await expect(
    cards.nth(0).getByText('Written: Make sure the pain is real before you build.'),
  ).toBeVisible();
  await expect(
    cards.nth(1).getByText("Written: Don't make OAuth integrations your core value."),
  ).toBeVisible();
  await expect(page.getByText('Writing…')).toHaveCount(0);
  await expect(
    cards.nth(0).getByText('Built for trust · aims for bookmarks · short'),
  ).toBeVisible();

  const notWritten = page.getByRole('list', { name: 'Not written' });
  await notWritten.getByRole('button', { name: /^Write “Charge at least 20 euros/ }).click();
  await expect(cards).toHaveCount(3);
  expect(picked).toHaveLength(1);
  await expect(cards.nth(1).getByText('Writing…')).toBeVisible();
  await expect(notWritten).toHaveCount(0);
  runSeedScript('planned_brief.py', ['written', briefId]);
  await expect(cards.nth(1).getByText(/^Written: Charge at least 20 euros/)).toBeVisible();

  await cards.nth(0).getByRole('link', { name: /^Open/ }).click();
  await expect(page).toHaveURL(/\/posts\/post_/);

  const place = page.getByRole('navigation', { name: 'Posts from your brief' });
  await expect(place.getByText('1 of 3')).toBeVisible();
  await place.getByRole('link', { name: 'Next post' }).click();
  await expect(place.getByText('2 of 3')).toBeVisible();
  await expect(page.getByRole('textbox', { name: 'Post text' })).toHaveValue(
    /^Written: Charge at least 20 euros/,
  );
  await place.getByRole('link', { name: 'Posts from your brief' }).click();
  await expect(page).toHaveURL(new RegExp(`/briefs/${briefId}$`));
});

test('recent briefs on New post show a brief writing, update when it is written, and open its page', async ({
  page,
}) => {
  const ideaIds = runSeedScript('planned_brief.py', ['ideas', briefId])
    .trim()
    .split(/\s+/)
    .slice(0, 2);
  runSeedScript('planned_brief.py', ['writing', briefId, ...ideaIds]);
  await page.goto('/new');

  const recent = page.getByRole('region', { name: 'Recent briefs' });
  const row = recent.getByRole('link', { name: /^Three things my failed SaaS taught me/ });
  await expect(row).toContainText('Writing…');

  runSeedScript('planned_brief.py', ['written', briefId]);
  await expect(row).toContainText('2 of 3 written', { timeout: 20_000 });

  await row.click();
  await expect(page).toHaveURL(new RegExp(`/briefs/${briefId}$`));
  await expect(page.getByText('2 of 3 written')).toBeVisible();
});

test('a draft is discarded from its card and from its page, and its idea is offered again', async ({
  page,
}) => {
  runSeedScript('planned_brief.py', ['writing', briefId]);
  runSeedScript('planned_brief.py', ['written', briefId]);
  await page.goto(`/briefs/${briefId}`);

  const cards = page.getByRole('list', { name: 'Posts' }).getByRole('listitem');
  await expect(cards).toHaveCount(3);
  await expect(page.getByText('3 of 3 written')).toBeVisible();

  await page.getByRole('button', { name: 'Discard “Charge at least 20 euros a month”' }).click();
  const confirm = page.getByRole('alertdialog');
  await expect(confirm.getByText('Discard this post?')).toBeVisible();
  await expect(confirm.getByText('Its versions are deleted for good.')).toBeVisible();
  await confirm.getByRole('button', { name: 'Discard' }).click();

  await expect(cards).toHaveCount(2);
  await expect(page.getByText('2 of 3 written')).toBeVisible();
  const notWritten = page.getByRole('list', { name: 'Not written' });
  await expect(
    notWritten.getByRole('listitem', { name: 'Charge at least 20 euros a month' }),
  ).toBeVisible();
  await expect(cards.nth(1)).toHaveAttribute(
    'aria-label',
    "Don't make OAuth integrations your core value",
  );

  await cards.nth(0).getByRole('link', { name: /^Open/ }).click();
  const place = page.getByRole('navigation', { name: 'Posts from your brief' });
  await expect(place.getByText('1 of 2')).toBeVisible();
  await page
    .getByRole('article', { name: 'Text' })
    .getByRole('button', { name: 'Discard' })
    .click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Discard' }).click();

  await expect(page).toHaveURL(new RegExp(`/briefs/${briefId}$`));
  await expect(cards).toHaveCount(1);
  await expect(page.getByText('1 of 3 written')).toBeVisible();
  await expect(notWritten.getByRole('listitem')).toHaveCount(2);
});

test('a post of a brief of several ideas is scheduled through "Post to…" and shows as scheduled', async ({
  page,
}) => {
  runSeedScript('connect_x.py');
  runSeedScript('planned_brief.py', ['writing', briefId]);
  runSeedScript('planned_brief.py', ['written', briefId]);
  await page.goto(`/briefs/${briefId}`);

  const cards = page.getByRole('list', { name: 'Posts' }).getByRole('listitem');
  await expect(cards).toHaveCount(3);
  await cards.nth(0).getByRole('button', { name: 'Post to…', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('Schedule', { exact: true }).click();
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const date = [
    tomorrow.getFullYear(),
    String(tomorrow.getMonth() + 1).padStart(2, '0'),
    String(tomorrow.getDate()).padStart(2, '0'),
  ].join('-');
  await dialog.getByLabel('Date').fill(date);
  await dialog.getByLabel('Time').fill('09:00');
  await dialog.getByRole('button', { name: /^Schedule for / }).click();
  await expect(dialog).toBeHidden();

  await expect(cards.nth(0).getByText('Scheduled', { exact: true })).toBeVisible();
  await expect(cards.nth(0).getByRole('button', { name: 'Post to…', exact: true })).toHaveCount(0);
  await expect(cards.nth(1).getByRole('button', { name: 'Post to…', exact: true })).toBeVisible();

  await cards.nth(0).getByRole('link', { name: /^Open/ }).click();
  await expect(page).toHaveURL(/\/posts\/post_/);
  await expect(
    page.getByRole('region', { name: 'Scheduled' }).getByText(/^Scheduled for /),
  ).toBeVisible();
  await expect(
    page.getByRole('navigation', { name: 'Posts from your brief' }).getByText('1 of 3'),
  ).toBeVisible();
});
