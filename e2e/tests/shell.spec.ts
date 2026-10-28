import { expect, test, type Page } from '@playwright/test';

test.describe('logged out', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('visiting /new redirects to /login', async ({ page }) => {
    await page.goto('/new');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  });
});

test.describe('logged in', () => {
  const sidebar = (page: Page) => page.getByRole('navigation', { name: 'Main' }).first();
  const userMenu = (page: Page) => page.getByRole('button', { name: 'User menu' }).first();

  // A stored refusal keeps the Analytics consent banner, shown only with PostHog configured, off the page.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() =>
      localStorage.setItem('pumpkit:analytics-consent', JSON.stringify('denied')),
    );
  });

  test('/ and /home open New post, with the Brief box and the user name', async ({ page }) => {
    for (const path of ['/', '/home']) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/new$/);
      await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
      await expect(
        page.getByRole('region', { name: 'Write a Post' }).getByLabel('Brief'),
      ).toBeVisible();
      await expect(page.getByText('E2E User').first()).toBeVisible();
    }
  });

  test('the sidebar leads to every page and marks the one on screen', async ({ page }) => {
    await page.goto('/new');
    const nav = sidebar(page);
    await expect(nav.getByRole('link', { name: 'New post' })).toHaveAttribute(
      'aria-current',
      'page',
    );

    for (const [name, path, title] of [
      [/^Persona/, '/persona', 'Persona'],
      ['Posts', '/posts', 'Posts'],
      ['Settings', '/settings', 'Settings'],
    ] as const) {
      await nav.getByRole('link', { name }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible();
      await expect(nav.getByRole('link', { name })).toHaveAttribute('aria-current', 'page');
    }
  });

  test('with an empty Persona, New post offers to set it up and Persona counts 0/3', async ({
    page,
  }) => {
    await page.goto('/new');
    const writer = page.getByRole('region', { name: 'Write a Post' });
    await expect(
      sidebar(page).getByRole('link', { name: 'Persona, 0 of 3 Inspiration authors' }),
    ).toBeVisible();
    await expect(page.getByRole('link', { name: 'Persona: empty, set it up' })).toBeVisible();

    await writer.getByRole('link', { name: 'Set up your Persona' }).click();

    await expect(page).toHaveURL(/\/persona$/);
    await expect(page.getByRole('region', { name: 'How your posts sound' })).toBeVisible();
  });

  test('the New Post shortcut opens an empty New post from another page', async ({ page }) => {
    await page.goto('/persona');
    await expect(page.getByRole('heading', { level: 1, name: 'Persona' })).toBeVisible();

    await page.keyboard.press('ControlOrMeta+Shift+O');

    await expect(page).toHaveURL(/\/new$/);
    await expect(page.getByLabel('Brief')).toHaveValue('');
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('the sidebar is a drawer opened from the header', async ({ page }) => {
      await page.goto('/new');
      await expect(page.getByRole('heading', { level: 1, name: 'New post' })).toBeVisible();
      await expect(sidebar(page)).toBeHidden();

      await page.getByRole('button', { name: 'Open sidebar' }).click();
      const drawer = page.getByRole('dialog', { name: 'Sidebar' });
      await drawer.getByRole('link', { name: /^Persona/ }).click();

      await expect(page).toHaveURL(/\/persona$/);
      await expect(drawer).toBeHidden();
      const width = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(width).toBeLessThanOrEqual(390);
    });
  });

  test('user menu opens Account and Billing dialogs', async ({ page }) => {
    await page.goto('/new');
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
    await page.goto('/new');
    await userMenu(page).click();
    await page.getByRole('menuitem', { name: 'Theme' }).hover();
    await page.getByRole('menuitemradio', { name: 'Dark' }).click();
    await expect(page.locator('html')).toHaveClass(/dark/);
    await page.reload();
    await expect(page.locator('html')).toHaveClass(/dark/);
  });
});
