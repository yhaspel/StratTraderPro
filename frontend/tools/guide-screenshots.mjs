/**
 * Regenerate the step screenshots embedded in the Guides tab.
 *
 *   node tools/guide-screenshots.mjs
 *
 * WHY A SCRIPT AND NOT A MANUAL CAPTURE
 * -------------------------------------
 * The screenshots are documentation of *this* UI. Captured by hand they rot
 * silently the first time a component is restyled, and — captured from a real
 * deployment — they carry a real user's display name, email, broker accounts and
 * webhook URLs into a public repo. This script drives the production bundle with
 * every /api/ call stubbed by the fixtures below, so the output shows the real
 * components rendering fictional data, and any of us can regenerate the whole
 * set after a redesign.
 *
 * Prerequisites: `pnpm build` (or `ng build`) has produced dist/strattraderpro/browser.
 * Chromium comes from PLAYWRIGHT_BROWSERS_PATH in this environment.
 */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync, mkdirSync } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '@playwright/test';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const DIST = join(ROOT, 'dist/strattraderpro/browser');
const OUT = join(ROOT, 'src/assets/guides/img');
const PORT = 4599;

const MIME = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
  '.png': 'image/png', '.woff2': 'font/woff2', '.txt': 'text/plain',
};

// ---------------------------------------------------------------------------
// Fixtures — fictional data only. No real account, symbol position or secret.
// ---------------------------------------------------------------------------
const USER = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'trader@example.com',
  display_name: 'Sample Trader',
  is_verified: true,
  mfa_enabled: true,
  is_staff: true,
};

const STRATEGY_ID = '11111111-1111-4111-8111-111111111111';
const STRATEGY_ID2 = '22222222-2222-4222-8222-222222222222';

const STRATEGIES = [
  {
    id: STRATEGY_ID,
    name: 'Momentum Breakout (sample)',
    slug: 'momentum-breakout-sample',
    description_short: 'Buys 20-day breakouts, exits on a 10-day low.',
    is_system: true, is_enabled: true, is_community_tested: true,
    type: 'system', has_webhook_config: true,
    created_at: '2026-01-04T10:00:00Z', updated_at: '2026-01-04T10:00:00Z',
    files: [{ kind: 'PINE', filename: 'strategy.pine', sha256: 'a'.repeat(64), size_bytes: 2048, uploaded_at: '2026-01-04T10:00:00Z' }],
  },
  {
    id: STRATEGY_ID2,
    name: 'Mean Reversion RSI (sample)',
    slug: 'mean-reversion-rsi-sample',
    description_short: 'User-uploaded strategy. Untested.',
    is_system: false, is_enabled: false, is_community_tested: false,
    type: 'user', has_webhook_config: false,
    created_at: '2026-02-11T10:00:00Z', updated_at: '2026-02-11T10:00:00Z',
    files: [],
  },
];

const DESC_TEXT = `Momentum Breakout (sample)
==========================

Idea
----
Long-only trend continuation. The strategy buys a close above the highest
high of the last 20 sessions and exits on a close below the lowest low of
the last 10, so winners are held while the trend persists and losers are
cut on the first structural break.

Universe and timeframe
----------------------
Liquid US large caps, daily bars. Signals are evaluated on bar close only;
intrabar touches of the level are ignored.

Position sizing
---------------
One unit per signal. Actual size is decided by your StratTraderPro risk
profile, not by the Pine script — the alert carries intent, the platform
decides quantity.

Known weaknesses
----------------
Chops badly in range-bound regimes. Check the Market Regime badge before
enabling: CHOP is where this strategy gives back its trend profits.
`;

// Shape mirrors apps.strategies.services.default_payload_template() — the guides
// screenshot the real starter template, not an invented one.
const TEMPLATE_JSON = {
  strategy: 'momentum-breakout-sample',
  action: 'buy',
  symbol: 'AAPL',
  qty: 1,
  order_type: 'MKT',
  sig: 'PASTE_YOUR_SECRET_HERE',
  idempotency_key: 'tv-{{strategy.order.id}}-{{time}}',
};

const REGIME_LABELS = ['BULL', 'BULL', 'CHOP', 'CHOP', 'BEAR', 'CHOP', 'BULL'];
const regimeHistory = Array.from({ length: 84 }, (_, i) => ({
  ts: new Date(Date.UTC(2026, 4, 1 + i)).toISOString(),
  scope: 'MARKET',
  label: REGIME_LABELS[i % REGIME_LABELS.length],
  rule_bucket: 'NEUTRAL',
  rule_score: 0.1,
  hmm_state: 1,
  hmm_probs: {},
  top_features: [],
  model: { version: '2026-05-01', degraded: false },
}));

const CURRENT_REGIME = {
  ts: '2026-07-28T22:30:00Z',
  scope: 'MARKET',
  label: 'BULL',
  rule_bucket: 'RISK_ON',
  rule_score: 0.62,
  hmm_state: 0,
  hmm_probs: { '0': 0.71, '1': 0.18, '2': 0.08, '3': 0.03 },
  top_features: [
    { name: 'spy_trend', z: 1.42 }, { name: 'vix_level', z: -0.98 },
    { name: 'hy_oas', z: -0.61 }, { name: 'yield_curve', z: 0.33 },
    { name: 'dxy_trend', z: -0.21 },
  ],
  model: { version: '2026-05-01', degraded: false },
};

const ok = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ data }) });

/** Longest-match-first so `/strategies/<id>/files/DESC/` wins over `/strategies/`. */
const ROUTES = [
  ['/api/v1/auth/refresh/', () => ok({ access: 'demo-access-token', refresh: '', user: USER })],
  ['/api/v1/users/me/', () => ok({
    ...USER, created_at: '2026-01-01T00:00:00Z',
    profile: {
      timezone: 'Asia/Jerusalem', language: 'en', notification_email: true,
      default_broker_id: null, terms_version_accepted: 'v1',
    },
  })],
  ['/api/v1/onboarding/status/', () => ok({
    mfa_enrolled: true, broker_connected: true, strategy_ready: true,
    first_fill_seen: true, complete: true,
  })],
  ['/api/v1/terms/current/', () => ok({
    tos_version: 'v1', tos_url: '/terms', privacy_version: 'v1',
    privacy_url: '/privacy', needs_acceptance: false,
  })],
  ['/api/v1/risk/killswitches/', () => ok([])],
  ['/api/v1/regime/current/', () => ok(CURRENT_REGIME)],
  ['/api/v1/regime/history/', () => ok(regimeHistory)],
  ['/api/v1/regime/model/', () => ok({
    version: '2026-05-01', n_states: 4, trained_at: '2026-05-01T07:00:00Z',
    holdout_ll: -412.7, degraded: false, source_configured: true,
  })],
  ['/api/v1/sentiment/market/', () => ok({
    polarity: 0.18, confidence: 0.62, article_count: 41,
    ts: '2026-07-29T18:00:00Z', degraded: false,
  })],
  ['/api/v1/sentiment/articles/', () => ok([])],
  ['/api/v1/positions/', () => ok([])],
  ['/api/v1/fills/', () => ok([])],
  ['/api/v1/brokers/', () => ok([
    { id: 'b1', broker: 'ALPACA', label: 'Alpaca paper', status: 'CONNECTED', stream_status: 'CONNECTED', paper: true },
  ])],
  [`/api/v1/strategies/${STRATEGY_ID}/files/PINE/`, () => ({
    status: 200, contentType: 'text/plain',
    body: '//@version=5\nstrategy("Momentum Breakout (sample)", overlay=true)\n\nlen = input.int(20, "Breakout lookback")\nexitLen = input.int(10, "Exit lookback")\n\nupper = ta.highest(high, len)[1]\nlower = ta.lowest(low, exitLen)[1]\n\nif close > upper\n    strategy.entry("Long", strategy.long)\nif close < lower\n    strategy.close("Long")\n',
  })],
  [`/api/v1/strategies/${STRATEGY_ID}/files/DESC/`, () => ({ status: 200, contentType: 'text/plain', body: DESC_TEXT })],
  [`/api/v1/strategies/${STRATEGY_ID}/files/WEBHOOK_TEMPLATE/`, () => ({
    status: 200, contentType: 'application/json', body: JSON.stringify(TEMPLATE_JSON),
  })],
  [`/api/v1/strategies/${STRATEGY_ID}/`, () => ok(STRATEGIES[0])],
  ['/api/v1/strategies/', () => ok(STRATEGIES)],
  ['/api/v1/admin/health/', () => ok({
    queue_depths: { celery: 0, backtest: 0 },
    broker_streams: { CONNECTED: 1 },
    hmm_model_age_seconds: 89400,
    sentiment_backlog: { depth: 12, oldest_age_min: 3.4, alert: false },
    db_ok: true, redis_ok: true,
    verifier: { last_verified_id: 80, run_at: '2026-07-29T08:00:00Z', result: 'ok' },
    active_halts: { total: 0, platform: false },
    flags_overridden: 0,
    regime_source_configured: true,
    generated_at: '2026-07-29T18:25:45Z',
  })],
  ['/api/v1/admin/platform/', () => ok({ halted: false, note: '' })],
];

function serveStatic() {
  return createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    let rel = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '');
    let file = join(DIST, rel);
    if (!extname(file) || !existsSync(file)) { file = join(DIST, 'index.html'); }
    try {
      const body = await readFile(file);
      res.writeHead(200, { 'Content-Type': MIME[extname(file)] ?? 'application/octet-stream' });
      res.end(body);
    } catch {
      res.writeHead(404); res.end('not found');
    }
  }).listen(PORT);
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const server = serveStatic();
  // This repo's @playwright/test is newer than the Chromium build cached in the
  // sandbox, so point at the cached binary instead of downloading one. Locally,
  // drop STP_CHROMIUM and Playwright resolves its own browser as usual.
  const executablePath = process.env.STP_CHROMIUM || undefined;
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    deviceScaleFactor: 2,
  });

  // Optional offline webfont cache. In a sandbox with no egress to Google Fonts
  // the capture would silently fall back to a system face, so the screenshots
  // would not match the app. Populate a directory with fonts.css (rewritten to
  // https://fonts.gstatic.com/local/<file>.woff2) plus the woff2 files and point
  // STP_FONT_CACHE at it. Unset (the normal case) = fonts load from the network.
  const fontCache = process.env.STP_FONT_CACHE;
  if (fontCache) {
    await page.route('https://fonts.googleapis.com/**', async (route) =>
      route.fulfill({ status: 200, contentType: 'text/css', body: await readFile(join(fontCache, 'fonts.css')) }));
    await page.route('https://fonts.gstatic.com/**', async (route) => {
      const name = new URL(route.request().url()).pathname.split('/').pop();
      try {
        return route.fulfill({ status: 200, contentType: 'font/woff2', body: await readFile(join(fontCache, name)) });
      } catch {
        return route.fulfill({ status: 404, body: '' });
      }
    });
  }

  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    const hit = ROUTES.find(([prefix]) => path.startsWith(prefix));
    if (hit) { return route.fulfill(hit[1]()); }
    return route.fulfill(ok(null));
  });

  const shots = [
    { name: 'nav-guides', url: '/dashboard', clip: { x: 0, y: 0, width: 1280, height: 54 } },
    { name: 'strategies-list', url: '/strategies', selector: 'table' },
    { name: 'strategy-detail-description', url: `/strategies/${STRATEGY_ID}`, selector: '#desc-heading ~ pre' },
    { name: 'strategy-detail-template', url: `/strategies/${STRATEGY_ID}`, selector: '#tmpl-heading ~ pre' },
    { name: 'settings-timezone', url: '/settings/profile', selector: 'form' },
    { name: 'dashboard-regime', url: '/dashboard', selector: 'app-regime-badge' },
    { name: 'admin-health', url: '/admin/health', fullPage: false },
  ];

  for (const shot of shots) {
    await page.goto(`http://localhost:${PORT}${shot.url}`, { waitUntil: 'networkidle' });
    // Barlow / IBM Plex Mono come from Google Fonts. Without this wait the
    // capture races the webfont swap and half the set ships in a fallback face.
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(900);
    const target = shot.selector ? page.locator(shot.selector).first() : page;
    if (shot.selector) { await target.waitFor({ state: 'visible', timeout: 15000 }); }
    const opts = { path: join(OUT, `${shot.name}.png`) };
    if (shot.clip) { opts.clip = shot.clip; }
    if (!shot.selector && shot.fullPage !== undefined) { opts.fullPage = shot.fullPage; }
    await (shot.selector ? target : page).screenshot(opts);
    console.log('wrote', shot.name + '.png');
  }

  await browser.close();
  server.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
