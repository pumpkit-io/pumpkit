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

  test('the sidebar logo slides and fades without a jump or flash', async ({ page }) => {
    await page.goto('/home');
    const aside = page.locator('aside').first();
    await expect(aside.locator('img').first()).toBeVisible();
    const box = (await aside.boundingBox())!;

    // Samples the logo every frame: position, the opacity it renders at, and the wordmark's.
    const framesWhile = async (toggle: () => Promise<void>) => {
      await page.evaluate(() => {
        const aside = document.querySelector('aside')!;
        const img = aside.querySelector('img')!;
        const frames: { x: number; op: number; name: number }[] = [];
        (window as unknown as { frames_: typeof frames }).frames_ = frames;
        const t0 = performance.now();
        const tick = () => {
          let op = 1;
          for (let el: Element | null = img; el && el !== aside; el = el.parentElement)
            op *= parseFloat(getComputedStyle(el).opacity);
          const name = img.nextElementSibling;
          frames.push({
            x: img.getBoundingClientRect().x,
            op,
            name: name ? parseFloat(getComputedStyle(name).opacity) : 0,
          });
          if (performance.now() - t0 < 600) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
      await toggle();
      await page.waitForTimeout(700);
      return page.evaluate(
        () => (window as unknown as { frames_: { x: number; op: number; name: number }[] }).frames_,
      );
    };

    await page.mouse.move(box.x + 100, box.y + 300);
    const closing = await framesWhile(() =>
      page.getByRole('button', { name: 'Close sidebar' }).click(),
    );
    await page.mouse.move(box.x + 28, box.y + 300);
    const opening = await framesWhile(() =>
      aside.getByRole('button', { name: 'Open sidebar' }).click(),
    );

    for (const frames of [closing, opening]) {
      for (let i = 1; i < frames.length; i++) {
        const [prev, cur] = [frames[i - 1], frames[i]];
        if (prev.op > 0.05) expect(Math.abs(cur.x - prev.x)).toBeLessThanOrEqual(2);
        if (cur.op > 0.05) expect(prev.name - cur.name).toBeLessThanOrEqual(0.5);
        const next = frames[i + 1];
        if (next) {
          const flash =
            Math.abs(cur.op - prev.op) > 0.3 &&
            Math.abs(next.op - cur.op) > 0.3 &&
            Math.sign(cur.op - prev.op) !== Math.sign(next.op - cur.op);
          expect(flash).toBe(false);
        }
      }
    }
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
