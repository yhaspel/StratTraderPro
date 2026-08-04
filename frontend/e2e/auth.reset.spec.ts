import { expect, test } from '@playwright/test';
import { SAMPLE_TOKEN_PAIR, installAuthMock, ok } from './helpers/mock-api';

test.describe('password reset', () => {
  test('request → confirmation → auto-login via reset token', async ({ page }) => {
    const mock = await installAuthMock(page);
    // In a real stack the email link contains the token; we capture the token
    // handed to the reset endpoint and shove it straight into the confirm URL.
    let capturedToken = 'prv_sample_reset_token';
    mock.on('/auth/password/reset/', async (route) => {
      // Backend always 200s to avoid email enumeration.
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { status: 'ok' } }),
      });
    });
    mock.on('/auth/password/reset/confirm/', ok(SAMPLE_TOKEN_PAIR));

    await page.goto('/password-reset');
    await page.getByLabel('Email address').fill('trader@example.com');
    await page.getByRole('button', { name: /send reset link/i }).click();

    await expect(page.getByText(/if an account with that email exists/i)).toBeVisible();
    expect(mock.callCount('/auth/password/reset/')).toBe(1);

    // Simulate clicking the token link from the email.
    await page.goto(`/password-reset/confirm?token=${capturedToken}`);
    await page.getByLabel('New password', { exact: true }).fill('correct horse battery staple');
    await page.getByLabel('Confirm new password').fill('correct horse battery staple');
    await page.getByRole('button', { name: /reset password/i }).click();

    // Successful confirm issues JWT pair and navigates to dashboard.
    await expect(page).toHaveURL(/\/dashboard$/);
    expect(mock.callCount('/auth/password/reset/confirm/')).toBe(1);
  });
});
