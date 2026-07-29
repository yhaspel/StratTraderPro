import { expect, test } from '@playwright/test';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

/**
 * The Guides tab is a primary nav destination (M12 §7.1) and the one place a
 * user is sent when something else confuses them — an inaccessible help system
 * fails exactly the people most likely to need it.
 */
test.describe('a11y: guides', () => {
  test('/guides — no critical/serious axe violations', async ({ page }) => {
    await seedAuthedPage(page);

    await page.goto('/guides');

    await expect(page.getByRole('heading', { level: 1, name: 'Guides' })).toBeVisible();
    // Section grouping is what makes the index navigable rather than a wall of links.
    await expect(page.getByRole('heading', { level: 2, name: 'Start here' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });

  test('/guides/:slug — renders an article with no critical/serious violations', async ({ page }) => {
    await seedAuthedPage(page);

    await page.goto('/guides/getting-started');

    await expect(
      page.getByRole('heading', { level: 1, name: 'Getting started, end to end' }),
    ).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });

  test('/help/:slug still resolves — the M10.5 links are bookmarked', async ({ page }) => {
    await seedAuthedPage(page);

    await page.goto('/help/mfa');

    await expect(page).toHaveURL(/\/guides\/mfa$/);
  });
});
