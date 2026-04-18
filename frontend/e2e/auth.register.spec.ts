import { expect, test } from '@playwright/test';
import { fail, installAuthMock, ok } from './helpers/mock-api';

test.describe('register', () => {
  test('happy path — redirects to resend-verification page', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on('/auth/register/', ok({ id: 'new-id', email: 'new@example.com' }, 201));
    mock.on('/auth/resend-verification/', ok({ status: 'ok' }));

    await page.goto('/register');
    await page.getByLabel('Email address').fill('new@example.com');
    await page.getByLabel('Display name').fill('New User');
    await page.getByLabel('Password').fill('correct horse battery staple');
    await page.getByRole('button', { name: /create account/i }).click();

    await expect(page).toHaveURL(/\/resend-verification\?email=new%40example\.com$/);
    await expect(page.getByRole('heading', { name: /check your inbox/i })).toBeVisible();
    expect(mock.callCount('/auth/register/')).toBe(1);
  });

  test('duplicate email — backend returns 202 status envelope, still routes forward', async ({ page }) => {
    const mock = await installAuthMock(page);
    // Anti-enumeration: backend always succeeds shape-wise for duplicates.
    mock.on('/auth/register/', ok({ status: 'pending_verification' }, 202));
    mock.on('/auth/resend-verification/', ok({ status: 'ok' }));

    await page.goto('/register');
    await page.getByLabel('Email address').fill('dup@example.com');
    await page.getByLabel('Display name').fill('Dup');
    await page.getByLabel('Password').fill('correct horse battery staple');
    await page.getByRole('button', { name: /create account/i }).click();

    await expect(page).toHaveURL(/\/resend-verification/);
  });

  test('weak password — shows PASSWORD_WEAK banner, stays on page', async ({ page }) => {
    const mock = await installAuthMock(page);
    mock.on(
      '/auth/register/',
      fail('PASSWORD_WEAK', 'Password does not meet policy.', 400, {
        password: ['This password is too common.'],
      }),
    );

    await page.goto('/register');
    await page.getByLabel('Email address').fill('weak@example.com');
    await page.getByLabel('Display name').fill('Weak');
    // 12+ chars to pass the client-side minLength; server rejects anyway.
    await page.getByLabel('Password').fill('password1234');
    await page.getByRole('button', { name: /create account/i }).click();

    await expect(page).toHaveURL(/\/register$/);
    await expect(page.getByRole('alert')).toBeVisible();
  });
});
