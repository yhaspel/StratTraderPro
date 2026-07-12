import { expect, test } from '@playwright/test';
import { ok } from '../helpers/mock-api';
import { expectNoSeriousA11yViolations, seedAuthedPage } from './a11y.helpers';

test.describe('a11y: admin', () => {
  test('/admin — no critical/serious axe violations', async ({ page }) => {
    // Staff user required — adminGuard gates the /admin routes on is_staff.
    const mock = await seedAuthedPage(page, { staff: true });
    mock.on('/admin/health/', ok(null));
    mock.on('/admin/platform/status/', ok(null));

    await page.goto('/admin');

    // Page-identifying locator — proves we reached /admin (staff), not /login
    // or the /dashboard redirect a non-staff user would hit.
    await expect(page.getByRole('heading', { level: 1, name: 'Admin portal' })).toBeVisible();

    await expectNoSeriousA11yViolations(page);
  });
});
