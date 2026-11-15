import { test as base } from '@playwright/test';

export { expect, type Page, type Response } from '@playwright/test';

export const test = base.extend<{ realDraftStart: boolean; draftStartStub: void }>({
  realDraftStart: [false, { option: true }],
  draftStartStub: [
    async ({ context, realDraftStart }, use) => {
      // The stack's twitterapi.io key and model are real and cost money, and every sign-in starts a draft.
      if (!realDraftStart) {
        await context.route('**/api/v1/positioning/draft/start', (route) =>
          route.fulfill({ status: 202, body: '' }),
        );
      }
      await use();
    },
    { auto: true },
  ],
});
