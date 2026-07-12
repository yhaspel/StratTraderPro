import { expect, test } from '@playwright/test';
import { ok } from '../helpers/mock-api';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

test.describe('a11y: dashboard', () => {
  test('/dashboard — no critical/serious axe violations', async ({ page }) => {
    const mock = await seedAuthedPage(page);
    // DashboardFacade.loadSnapshot
    mock.on('/positions/', ok([]));
    mock.on('/fills/', ok([]));
    mock.on('/brokers/', ok([]));
    // RegimeFacade
    mock.on('/regime/current/', ok(null));
    mock.on('/regime/history/', ok([]));
    mock.on('/regime/model/', ok(null));
    // SentimentFacade
    mock.on('/sentiment/market/', ok(null));
    mock.on('/sentiment/articles/', ok({ articles: [] }));
    // RiskFacade
    mock.on('/risk/killswitches/', ok([]));

    await page.goto('/dashboard');

    // Page-identifying locator — proves we reached /dashboard, not /login.
    await expect(page.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
