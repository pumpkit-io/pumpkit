import { expect, test } from '@playwright/test';

test.use({ storageState: { cookies: [], origins: [] } });

const toolName = /^(Claude|Claude Code|ChatGPT|Codex|Cursor|Gemini CLI)$/;

test('the headline does not queue tool names when animation frames are delayed', async ({
  page,
}) => {
  await page.clock.install();
  await page.addInitScript(() => {
    const requestFrame = window.requestAnimationFrame.bind(window);
    const held: FrameRequestCallback[] = [];
    window.requestAnimationFrame = (callback) =>
      requestFrame((time) => {
        if (document.documentElement.dataset.holdFrames) held.push(callback);
        else callback(time);
      });
    document.addEventListener('resume-animation-frames', () => {
      for (const callback of held.splice(0)) requestFrame(callback);
    });
  });
  await page.goto('/');
  const headline = page.getByRole('heading', { level: 1 });
  await expect(headline).toBeVisible();
  await page.clock.runFor(2000);
  await page.evaluate(() => {
    document.documentElement.dataset.holdFrames = 'true';
  });
  await page.clock.runFor(16_000);
  await page.evaluate(() => {
    delete document.documentElement.dataset.holdFrames;
    document.dispatchEvent(new Event('resume-animation-frames'));
  });
  await page.clock.runFor(150);

  const names = headline.getByText(toolName);
  expect(await names.count()).toBeLessThanOrEqual(2);
  await page.clock.runFor(600);
  await expect(names).toHaveCount(1);
  const current = await names.innerText();
  await page.clock.runFor(3200);
  await expect(names).toHaveCount(1);
  await expect(names).not.toHaveText(current);
});

test('the headline holds on the first tool with reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.clock.install();
  await page.goto('/');
  const names = page.getByRole('heading', { level: 1 }).getByText(toolName);
  await expect(names).toHaveText('Claude');
  await page.clock.runFor(16_000);
  await expect(names).toHaveText('Claude');
});
