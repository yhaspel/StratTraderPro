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

  test('/strategies/:id — screening panel in the ready state has no critical/serious axe violations', async ({
    page,
  }) => {
    // M16 §10.3 — the panel's rich state: criteria chips, a Run button and a
    // results table. The table is the part most likely to regress on a11y
    // (header scope, caption, contrast), so it is what we render here.
    const id = '11111111-1111-1111-1111-111111111111';
    const mock = await seedAuthedPage(page);

    mock.on(`/strategies/${id}/`, ok({
      id,
      name: 'Minervini Trend',
      slug: 'minervini-trend',
      description_short: 'Trend-following large caps.',
      is_system: false,
      is_enabled: true,
      is_community_tested: false,
      files: [],
    }));
    mock.on(`/strategies/${id}/files/PINE/`, (route) =>
      route.fulfill({ status: 200, contentType: 'text/plain', body: '//@version=5' }),
    );
    mock.on(`/strategies/${id}/files/DESC/`, (route) =>
      route.fulfill({ status: 200, contentType: 'text/plain', body: 'A trend strategy.' }),
    );
    mock.on(`/strategies/${id}/files/WEBHOOK_TEMPLATE/`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
    );
    mock.on('/marketdata/keys/', ok({
      fmp: { provider: 'FMP', configured: true, source: 'env' },
      fred: { provider: 'FRED', configured: false, source: null },
    }));
    mock.on(`/strategies/${id}/screen/criteria/`, ok({
      block_present: true,
      criteria: {
        market_cap: { gte: 2000000000 },
        sector: 'Technology',
        above_sma: [200],
        near_52w_high: 25,
        limit: 50,
      },
      fmp_params: { marketCapMoreThan: 2000000000, isActivelyTrading: true, isEtf: false, limit: 50 },
      derived: { above_sma: [200], near_52w_high: 25, min_history: 260 },
    }));
    mock.on(`/strategies/${id}/screen/runs/`, ok([{
      id: 'run-1',
      status: 'DONE',
      degraded: false,
      error_code: '',
      counts: { vendor_matches: 12, enriched: 12, returned: 1 },
      created_at: '2026-08-03T10:00:00Z',
      started_at: '2026-08-03T10:00:01Z',
      finished_at: '2026-08-03T10:00:09Z',
    }]));

    await page.goto(`/strategies/${id}`);

    await expect(page.getByRole('heading', { level: 1, name: 'Minervini Trend' })).toBeVisible();
    await expect(page.getByTestId('screening-panel')).toBeVisible();
    await expect(page.getByTestId('criteria-chips')).toBeVisible();
    await expect(page.getByTestId('run-screen')).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
