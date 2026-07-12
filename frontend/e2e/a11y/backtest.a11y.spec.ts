import { expect, test } from '@playwright/test';
import { ok } from '../helpers/mock-api';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

test.describe('a11y: backtest', () => {
  test('/backtest — no critical/serious axe violations', async ({ page }) => {
    const mock = await seedAuthedPage(page);
    mock.on('/backtest/strategies/', ok([]));
    // Empty runs list — the launcher renders its empty state (the paginated
    // footer, which reads `meta`, only renders when there ARE runs).
    mock.on('/backtest/runs/', ok([]));

    await page.goto('/backtest');

    // Page-identifying locator — proves we reached /backtest, not /login.
    await expect(page.getByRole('heading', { level: 1, name: 'Backtester' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
