import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

test('the Posts page loads with X to connect and the lists', async ({ page }) => {
  await page.goto('/posts');

  const xConnection = page.getByRole('region', { name: 'X connection' });
  await expect(xConnection.getByRole('button', { name: 'Connect X' })).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Upcoming' }).getByText(/nothing scheduled/i),
  ).toBeVisible();
  await expect(page.getByRole('region', { name: 'Published' })).toBeVisible();
});

test('a Thread scheduled from a Version is listed as one item', async ({ page }) => {
  runSeedScript('connect_x.py');
  runSeedScript('scheduled_thread.py');
  await page.goto('/posts');

  const upcoming = page.getByRole('region', { name: 'Upcoming' });
  await expect(upcoming.getByText('Thread, 2 Parts')).toBeVisible();
  await expect(upcoming.getByRole('listitem')).toHaveCount(1);
  await expect(upcoming.getByText('E2E Thread, Part two.')).toBeVisible();
});
