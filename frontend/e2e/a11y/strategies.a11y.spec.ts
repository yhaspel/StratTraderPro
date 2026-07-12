import { expect, test } from '@playwright/test';
import { ok } from '../helpers/mock-api';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

test.describe('a11y: strategies', () => {
  test('/strategies — no critical/serious axe violations', async ({ page }) => {
    const mock = await seedAuthedPage(page);
    mock.on('/strategies/', ok([]));

    await page.goto('/strategies');

    // Page-identifying locator — proves we reached /strategies, not /login.
    await expect(page.getByRole('heading', { level: 1, name: 'Strategies' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
