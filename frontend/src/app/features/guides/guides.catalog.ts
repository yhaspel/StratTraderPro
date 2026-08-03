/** Catalog for the Guides tab (M12 §7.1).
 *
 * ONE source of truth for "which guides exist". It backs three things that used
 * to drift apart:
 *
 *   1. the /guides index (sections + cards),
 *   2. the article viewer's allow-list — a slug not in this catalog is a 404
 *      before any HTTP call, which is what keeps `../secret` out of the fetch,
 *   3. prev/next links inside an article.
 *
 * Every entry MUST have a matching `src/assets/guides/<slug>.html`.
 * `scripts/check_guides_catalog.py` asserts that in both directions in CI, so
 * adding a file without listing it (orphan, unreachable from the index) or
 * listing one without the file (dead link) fails the build rather than shipping.
 */

export interface GuideArticle {
  slug: string;
  title: string;
  /** One line shown on the index card — what the reader gets out of it. */
  summary: string;
}

export interface GuideSection {
  key: string;
  title: string;
  articles: GuideArticle[];
}

export const GUIDE_SECTIONS: GuideSection[] = [
  {
    key: 'start',
    title: 'Start here',
    articles: [
      {
        slug: 'getting-started',
        title: 'Getting started, end to end',
        summary: 'The whole path: verify your account, turn on 2FA, connect a broker, add a strategy, see your first paper fill.',
      },
      {
        slug: 'mfa',
        title: 'Two-factor authentication',
        summary: 'Enrol an authenticator app and store your backup codes. Required before any trading endpoint will answer you.',
      },
      {
        slug: 'settings-profile',
        title: 'Profile settings: timezone, language, email',
        summary: 'Set the timezone every timestamp in the app is rendered in, and choose which emails you receive.',
      },
    ],
  },
  {
    key: 'brokers',
    title: 'Connect a broker',
    articles: [
      {
        slug: 'alpaca-paper-connect',
        title: 'Connect your Alpaca paper account',
        summary: 'Generate paper API keys at Alpaca and paste them into Settings → Brokers.',
      },
      {
        slug: 'tradestation-connect',
        title: 'Connect TradeStation',
        summary: 'The OAuth flow for TradeStation, and what to expect on the simulated account.',
      },
    ],
  },
  {
    key: 'strategies',
    title: 'Strategies and webhooks',
    articles: [
      {
        slug: 'using-a-strategy',
        title: 'Run a strategy end to end',
        summary: 'Read a strategy description, enable it, get its webhook URL, and wire the TradingView alert that fires it.',
      },
      {
        slug: 'strategy-upload',
        title: 'Upload your first strategy',
        summary: 'The three-file bundle (Pine, description, webhook template) and what the validator checks.',
      },
      {
        slug: 'webhook-payload-template',
        title: 'The webhook payload template',
        summary: 'Every field explained, where the template goes in TradingView, and how to test it before going live.',
      },
      {
        slug: 'tradingview-alert-config',
        title: 'Configure your TradingView alert',
        summary: 'Create the alert, paste the URL and the message body, and confirm the first delivery.',
      },
      {
        slug: 'strategy-screening',
        title: 'Screening for candidates',
        summary: 'Write a [screen] block into a strategy description, run it, and read the ranked candidates it returns.',
      },
    ],
  },
  {
    key: 'trading',
    title: 'Trading and risk',
    articles: [
      {
        slug: 'orders-page',
        title: 'The orders page',
        summary: 'Order states, fills, and how to tell a rejected order from a stuck one.',
      },
      {
        slug: 'risk-profile',
        title: 'Your risk profile',
        summary: 'Position sizing, per-trade and daily loss limits, and what happens when one trips.',
      },
      {
        slug: 'kill-switch',
        title: 'Kill switches',
        summary: 'Halt your own trading, what "flatten" does, and how a platform-wide halt differs.',
      },
    ],
  },
  {
    key: 'market',
    title: 'Market context',
    articles: [
      {
        slug: 'regime-badge',
        title: 'The market-regime badge',
        summary: 'What BULL / CHOP / BEAR / CRISIS mean and which features drive the call.',
      },
      {
        slug: 'market-regime-setup',
        title: 'Why Market Regime says "no data"',
        summary: 'The regime pipeline needs two market-data keys. How to check whether they are set, and what to do about it.',
      },
      {
        slug: 'sentiment',
        title: 'Market sentiment',
        summary: 'Where the news comes from, how articles are scored, and what the market polarity number means.',
      },
    ],
  },
  {
    key: 'backtest',
    title: 'Backtesting',
    articles: [
      {
        slug: 'running-your-first-backtest',
        title: 'Running your first backtest',
        summary: 'Pick a strategy and a window, launch the run, and find the result when it finishes.',
      },
      {
        slug: 'reading-the-tearsheet',
        title: 'Reading the tearsheet',
        summary: 'Which of the headline numbers actually tell you something, and which are noise.',
      },
      {
        slug: 'interpreting-pbo',
        title: 'Interpreting PBO',
        summary: 'Probability of backtest overfitting: what a high score is telling you about your parameter search.',
      },
    ],
  },
];

/** Flat, section-ordered list — drives prev/next and the slug allow-list. */
export const GUIDE_ARTICLES: GuideArticle[] = GUIDE_SECTIONS.flatMap(s => s.articles);

export const GUIDE_SLUGS: ReadonlySet<string> = new Set(GUIDE_ARTICLES.map(a => a.slug));

export function findGuide(slug: string): GuideArticle | undefined {
  return GUIDE_ARTICLES.find(a => a.slug === slug);
}
