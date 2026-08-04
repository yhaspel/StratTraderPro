import { expect, test } from '@playwright/test';
import { SAMPLE_TOKEN_PAIR, fail, installAuthMock, ok } from './helpers/mock-api';

async function fillLogin(page: import('@playwright/test').Page, email: string, password: string) {
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
}

test.describe('login', () => {
  test('happy path — redirects to /dashboard', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on('/auth/login/', ok(SAMPLE_TOKEN_PAIR));

    await page.goto('/login');
    await fillLogin(page, 'trader@example.com', 'correct horse battery staple');

    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test('unverified email — shows EMAIL_NOT_VERIFIED banner', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on(
      '/auth/login/',
      fail('EMAIL_NOT_VERIFIED', 'Please verify your email before signing in.', 403),
    );

    await page.goto('/login');
    await fillLogin(page, 'unverified@example.com', 'correct horse battery staple');

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('alert')).toContainText(/verify your email/i);
  });

  test('wrong password — shows INVALID_CREDENTIALS banner', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on('/auth/login/', fail('INVALID_CREDENTIALS', 'Invalid email or password.', 401));

    await page.goto('/login');
    await fillLogin(page, 'trader@example.com', 'wrongpassword0');

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('alert')).toContainText(/invalid email or password/i);
  });

  test('account locked — shows ACCOUNT_LOCKED banner', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on(
      '/auth/login/',
      fail('ACCOUNT_LOCKED', 'Account temporarily locked due to repeated failures.', 423),
    );

    await page.goto('/login');
    await fillLogin(page, 'locked@example.com', 'whatever123456');

    await expect(page.getByRole('alert')).toContainText(/locked/i);
  });

  test('rate limited — shows RATE_LIMITED banner', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on('/auth/login/', fail('RATE_LIMITED', 'Too many requests.', 429));

    await page.goto('/login');
    await fillLogin(page, 'trader@example.com', 'whatever123456');

    await expect(page.getByRole('alert')).toContainText(/too many/i);
  });
});
