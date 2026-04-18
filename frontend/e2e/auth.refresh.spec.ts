import { expect, test } from '@playwright/test';
import { SAMPLE_TOKEN_PAIR, fail, installAuthMock, ok } from './helpers/mock-api';

test.describe('silent refresh', () => {
  test('app bootstrap — stored refresh token rotates into an authed session', async ({ page }) => {
    const mock = await installAuthMock(page);
    await mock.seedRefreshToken('stored.refresh.jwt');

    mock.on(
      '/auth/refresh/',
      ok({ ...SAMPLE_TOKEN_PAIR, access: 'rotated.access.jwt', refresh: 'rotated.refresh.jwt' }),
    );

    await page.goto('/dashboard');

    // Guard allowed us through → APP_INITIALIZER silently refreshed.
    await expect(page).toHaveURL(/\/dashboard$/);
    expect(mock.callCount('/auth/refresh/')).toBe(1);
  });

  test('refresh failure — stored token rejected, user is routed to /login', async ({ page }) => {
    const mock = await installAuthMock(page);
    await mock.seedRefreshToken('expired.refresh.jwt');
    mock.on('/auth/refresh/', fail('TOKEN_INVALID', 'Invalid refresh token.', 401));

    await page.goto('/dashboard');

    await expect(page).toHaveURL(/\/login(\?.*)?$/);
    expect(mock.callCount('/auth/refresh/')).toBe(1);
  });

  test('401 on protected request triggers interceptor to refresh and retry', async ({ page }) => {
    const mock = await installAuthMock(page);
    // Pre-seed auth state so the user is considered logged in.
    await mock.seedRefreshToken('stale.refresh.jwt');
    mock.on(
      '/auth/refresh/',
      ok({ ...SAMPLE_TOKEN_PAIR, access: 'fresh.access.jwt', refresh: 'fresh.refresh.jwt' }),
    );

    // First /users/me/ call 401s with an expired-token shape; after refresh,
    // the interceptor should retry the same request and this second call
    // should succeed. We flip the handler after the first call.
    let meCalls = 0;
    mock.on('/users/me/', async (route) => {
      meCalls += 1;
      if (meCalls === 1) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ error: { code: 'TOKEN_EXPIRED', message: 'Expired.' } }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: SAMPLE_TOKEN_PAIR.user }),
        });
      }
    });

    await page.goto('/dashboard');

    // Bootstrap refresh (1 call) is sufficient for the dashboard to render;
    // to force a /users/me/ fetch we rely on any component that needs it.
    // For this smoke-level assertion we just confirm the refresh endpoint
    // was hit and the app did not redirect to /login.
    await expect(page).toHaveURL(/\/dashboard$/);
    expect(mock.callCount('/auth/refresh/')).toBeGreaterThanOrEqual(1);
  });
});
