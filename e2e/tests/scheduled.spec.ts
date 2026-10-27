import { expect, test } from '@playwright/test';
import { runSeedScript } from '../backend';

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

test('a two-Part Thread typed in the composer is scheduled as one item', async ({ page }) => {
  runSeedScript('connect_x.py');
  await page.goto('/scheduled');

  const composer = page.getByRole('region', { name: 'Post to X' });
  await composer.getByLabel('Post text').fill('E2E Thread, Part one.');
  await composer.getByRole('button', { name: 'Add a Part' }).click();
  await composer.getByRole('textbox', { name: 'Part 2' }).fill('E2E Thread, Part two.');
  // Tomorrow at 09:00 in the browser timezone, as the picker holds it.
  const tomorrow = new Date(Date.now() + 24 * 60 * 60 * 1000);
  const day = [
    tomorrow.getFullYear(),
    String(tomorrow.getMonth() + 1).padStart(2, '0'),
    String(tomorrow.getDate()).padStart(2, '0'),
  ].join('-');
  await composer.getByLabel('Date and time').fill(`${day}T09:00`);
  await composer.getByRole('button', { name: 'Schedule' }).click();

  const upcoming = page.getByRole('region', { name: 'Upcoming' });
  await expect(upcoming.getByText('Thread, 2 Parts')).toBeVisible();
  await expect(upcoming.getByRole('listitem')).toHaveCount(1);
  await expect(upcoming.getByText('E2E Thread, Part two.')).toBeVisible();
});
