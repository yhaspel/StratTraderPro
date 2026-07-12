/**
 * Shared setup for the axe-core a11y specs (M11 §7.10 / AC-11-11).
 *
 * `seedAuthedPage` reproduces the authed bootstrap every page shares:
 *   1. seed the persisted refresh token (auth.store hydrates from
 *      `stp_refresh_token`), so the authGuard's `refreshToken()` check passes;
 *   2. mock `/auth/refresh/` — the APP_INITIALIZER (AuthFacade.initSession)
 *      swaps it for a token pair, setting `isAuthenticated()`;
 *   3. mock `/onboarding/status/` and `/terms/current/` — both fetched by the
 *      ShellComponent on init. `/terms/current/` returns `needs_acceptance:false`
 *      so the new blocking terms modal never covers the page under test.
 *
 * Each spec then adds its own page-specific endpoints before `page.goto`.
 */
import { Page, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { AuthMock, SAMPLE_TOKEN_PAIR, SAMPLE_USER, installAuthMock, ok } from '../helpers/mock-api';

const ONBOARDING_COMPLETE = {
  mfa_enrolled: true,
  broker_connected: true,
  strategy_ready: true,
  first_fill_seen: true,
  complete: true,
};

const TERMS_OK = {
  needs_acceptance: false,
  tos_version: '',
  tos_url: '',
  privacy_version: '',
  privacy_url: '',
};

export interface SeedOptions {
  /** Return a staff user so the adminGuard lets /admin routes match. */
  staff?: boolean;
}

export async function seedAuthedPage(page: Page, opts: SeedOptions = {}): Promise<AuthMock> {
  const mock = await installAuthMock(page);
  await mock.seedRefreshToken('refresh.jwt.sample');

  const tokenPair = opts.staff
    ? { ...SAMPLE_TOKEN_PAIR, user: { ...SAMPLE_USER, is_staff: true } }
    : SAMPLE_TOKEN_PAIR;

  mock.on('/auth/refresh/', ok(tokenPair));
  mock.on('/onboarding/status/', ok(ONBOARDING_COMPLETE));
  mock.on('/terms/current/', ok(TERMS_OK));
  return mock;
}

/**
 * Run axe against the current page and fail on any critical/serious violation
 * (AC-11-11). Lower-impact (moderate/minor) findings are reported in the
 * message but do not fail the build.
 */
export async function expectNoSeriousA11yViolations(page: Page): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const blocking = results.violations.filter(
    (v) => v.impact === 'critical' || v.impact === 'serious',
  );
  const summary = blocking
    .map((v) => `  - [${v.impact}] ${v.id}: ${v.help} (${v.nodes.length} node(s))`)
    .join('\n');
  expect(blocking, `Critical/serious a11y violations:\n${summary}`).toEqual([]);
}
