import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

test('Settings offers to connect X', async ({ page }) => {
  await page.goto('/settings');

  const xAccount = page.getByRole('region', { name: 'X account' });
  await expect(xAccount.getByRole('button', { name: 'Connect X' })).toBeVisible();
});

test('the Posts page opens on an empty Scheduled tab', async ({ page }) => {
  await page.goto('/posts');

  await expect(page).toHaveURL(/\/posts\/scheduled$/);
  const tabs = page.getByRole('navigation', { name: 'Posts by status' });
  await expect(tabs.getByRole('link', { name: 'Scheduled 0' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.getByText(/Nothing scheduled\./)).toBeVisible();
});

test('a Thread scheduled from a Version is one row that expands into its Parts', async ({
  page,
}) => {
  runSeedScript('connect_x.py');
  runSeedScript('scheduled_thread.py');
  await page.goto('/posts/scheduled');

  const row = page.getByRole('listitem', { name: 'E2E Thread, Part one.' });
  await expect(row.getByText('Tomorrow')).toBeVisible();
  await expect(row.getByText(/Thread · 2 parts · Your profile/)).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Posts by status' })).toContainText(
    'Scheduled 1',
  );

  await row.getByRole('button', { name: 'Show every part' }).click();
  await expect(row.getByRole('listitem', { name: 'Part 2 of 2' })).toContainText(
    'E2E Thread, Part two.',
  );

  await row.getByRole('link', { name: 'E2E Thread, Part one.' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toContainText(
    'Posts / Scheduled / E2E Thread, Part one.',
  );
});
