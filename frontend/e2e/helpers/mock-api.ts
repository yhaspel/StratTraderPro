/**
 * Playwright helper that stubs the backend at `http://localhost:8777/api/v1/**`.
 *
 * Tests set per-endpoint handlers via `mock.on(path, handler)` before
 * navigation. Unhandled routes return a generic 500 to surface missing stubs.
 */
import { Page, Route } from '@playwright/test';

export const SAMPLE_USER = {
  id: '6f2e5a1d-0c9b-4b4e-8d6a-111111111111',
  email: 'trader@example.com',
  display_name: 'Jane Trader',
  is_verified: true,
};

export const SAMPLE_TOKEN_PAIR = {
  access: 'access.jwt.sample',
  refresh: 'refresh.jwt.sample',
  user: SAMPLE_USER,
  mfa_required: false,
};

type Handler = (route: Route) => Promise<void> | void;

const DEFAULT_HANDLERS: Record<string, Handler> = {
  // Health of the default: if not overridden, fail loudly so tests must opt in.
};

export interface AuthMock {
  on(endpoint: string, handler: Handler): void;
  reset(): void;
  /** Count calls for a given endpoint (exact tail-match against URL path). */
  callCount(endpoint: string): number;
  /** Seed localStorage refresh token before navigation. */
  seedRefreshToken(token: string): Promise<void>;
}

/**
 * Install the mock on a page. Must be called before `page.goto()`.
 * Endpoint keys are the trailing path (e.g. `/auth/login/`).
 */
export async function installAuthMock(page: Page): Promise<AuthMock> {
  const handlers: Record<string, Handler> = { ...DEFAULT_HANDLERS };
  const counts: Record<string, number> = {};

  const normalize = (pathname: string): string => {
    const idx = pathname.indexOf('/api/v1');
    return idx === -1 ? pathname : pathname.slice(idx + '/api/v1'.length);
  };

  await page.route(/\/api\/v1\/.*/, async (route) => {
    const url = new URL(route.request().url());
    const key = normalize(url.pathname);
    counts[key] = (counts[key] ?? 0) + 1;
    const handler = handlers[key];
    if (handler) {
      await handler(route);
      return;
    }
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({
        error: { code: 'NO_MOCK', message: `No mock installed for ${key}` },
      }),
    });
  });

  return {
    on(endpoint, handler) {
      handlers[endpoint] = handler;
    },
    reset() {
      for (const key of Object.keys(handlers)) delete handlers[key];
      for (const key of Object.keys(counts)) delete counts[key];
    },
    callCount(endpoint) {
      return counts[endpoint] ?? 0;
    },
    async seedRefreshToken(token: string) {
      await page.addInitScript((tok) => {
        window.localStorage.setItem('stp_refresh_token', tok);
      }, token);
    },
  };
}

// ---------------------------------------------------------------------------
// Canned response helpers
// ---------------------------------------------------------------------------
export const json = (body: unknown, status = 200): Handler => async (route) => {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
};

export const ok = (data: unknown, status = 200): Handler => json({ data }, status);

export const fail = (code: string, message: string, status = 400, details?: unknown): Handler =>
  json({ error: { code, message, ...(details ? { details } : {}) } }, status);
