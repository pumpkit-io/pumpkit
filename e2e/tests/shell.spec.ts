import { expect, test } from '@playwright/test';

test.describe('logged out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('visiting /home redirects to /login', async ({ page }) => {
    await page.goto('/home');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  });
});

test.describe('logged in', () => {
  const userMenu = (page: import('@playwright/test').Page) =>
    page.getByRole('button', { name: 'User menu' }).last();

  test('home shows the authors panel, the Brief box and the user name', async ({ page }) => {
    await page.goto('/home');
    await expect(page.getByRole('region', { name: 'Inspiration authors' })).toBeVisible();
    const writer = page.getByRole('region', { name: 'Write a Post' });
    await expect(writer.getByLabel('Brief')).toBeVisible();
    await expect(page.getByText('E2E User').first()).toBeVisible();
  });

  test('writing a Post is disabled with no Inspiration authors', async ({ page }) => {
    await page.goto('/home');
    const writer = page.getByRole('region', { name: 'Write a Post' });
    await expect(writer.getByText('Add an Inspiration author to write a Post.')).toBeVisible();
    await writer.getByLabel('Brief').fill('ship small things');
    await expect(writer.getByRole('button', { name: 'Write the Post' })).toBeDisabled();
  });

  test('user menu opens Account and Billing dialogs', async ({ page }) => {
    await page.goto('/home');
    await userMenu(page).click();
    await page.getByRole('menuitem', { name: 'Account' }).click();
    await expect(page.getByRole('dialog').getByText('Account', { exact: true })).toBeVisible();
    // Radix may ignore the first Escape while the dropdown's focus restore settles.
    await expect(async () => {
      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog')).toBeHidden({ timeout: 1_000 });
    }).toPass();

    await userMenu(page).click();
    await page.getByRole('menuitem', { name: 'Billing' }).click();
    await expect(page.getByRole('dialog').getByText('Billing', { exact: true })).toBeVisible();
  });

  test('theme choice persists across reloads', async ({ page }) => {
    await page.goto('/home');
    await userMenu(page).click();
    await page.getByRole('menuitem', { name: 'Theme' }).hover();
    await page.getByRole('menuitemradio', { name: 'Dark' }).click();
    await expect(page.locator('html')).toHaveClass(/dark/);
    await page.reload();
    await expect(page.locator('html')).toHaveClass(/dark/);
  });
});
