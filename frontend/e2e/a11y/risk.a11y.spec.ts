import { expect, test } from '@playwright/test';
import { ok } from '../helpers/mock-api';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

test.describe('a11y: risk', () => {
  test('/risk — no critical/serious axe violations', async ({ page }) => {
    const mock = await seedAuthedPage(page);
    mock.on('/risk/profile/', ok(null));
    mock.on('/risk/killswitches/', ok([]));
    mock.on('/risk/events/', ok([]));
    mock.on('/risk/sizing-decisions/', ok([]));

    await page.goto('/risk');

    // Page-identifying locator — proves we reached /risk, not /login.
    await expect(page.getByRole('heading', { level: 1, name: 'Risk management' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
