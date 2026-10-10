import { expect, test } from '@playwright/test';

test('the Scheduled page loads with X to connect, the composer and the lists', async ({ page }) => {
  await page.goto('/scheduled');

  const xConnection = page.getByRole('region', { name: 'X connection' });
  await expect(xConnection.getByRole('button', { name: 'Connect X' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Post to X' })).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Upcoming' }).getByText(/nothing scheduled/i),
  ).toBeVisible();
  await expect(page.getByRole('region', { name: 'Published' })).toBeVisible();
});
