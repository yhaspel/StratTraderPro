# Terms of Service — StratTraderPro

> ⚠️ **DRAFT — pending counsel review (M11 risk row §17).**
> This is a minimum-viable, engineer-authored draft written to unblock the beta
> acceptance flow (M11 §7.8). **It has not been reviewed by a lawyer.** Do not treat
> anything here as legal advice or a final legal position. Counsel sign-off is tracked
> as an open risk item, not a merge blocker — see
> `project-plan/11-hardening-and-load-test.md` §17.

**Version:** 1.0 (draft) — **Effective:** TBD (set on counsel sign-off)
**Applies to:** the StratTraderPro web application and API (the "Service")
**Mode in force:** **PAPER TRADING ONLY** — `ENABLE_LIVE_TRADING=false`. No real money moves.
**Companion:** `docs/legal/privacy-policy.md` (accepted together)
**Last reviewed:** 2026-07-12 (M11)

---

The app records your acceptance against the **version** above. When we publish a new
version, you will be asked to accept again before you can keep using the Service (see
§8). Keep this version line stable and bump it whenever the substance below changes —
`TermsAcceptance.tos_version` depends on it.

## 1. Eligibility & your account

- You must be at least 18 years old and legally able to enter a contract.
- You sign in with email/password (protected by TOTP multi-factor authentication) or
  with Google. You are responsible for everything that happens under your account.
- One human, one account. Don't share logins or let someone else operate your account.
- We may suspend or close an account that violates these Terms (see §7).

## 2. What StratTraderPro is (and is not)

StratTraderPro is a **tool** that executes your automated trading strategies when it
receives a webhook alert — for example, a TradingView-style alert posted to your
personal webhook URL. When a valid alert arrives, the Service translates it into an
order and submits it to **your** connected brokerage account.

**At this stage the Service is paper-trading only.** The only broker in the live path
is **Alpaca (paper)**; TradeStation is behind a flag and is off. `ENABLE_LIVE_TRADING`
is `false`. That means:

- **No real money is ever placed.** Orders go to a simulated (paper) brokerage
  environment. Balances, fills, and P&L are simulated.
- **We are not a broker-dealer, exchange, or investment adviser.** We do not hold your
  funds, take custody of assets, or route orders to a real market.
- **We do not give investment, financial, tax, or legal advice.** Nothing in the
  Service — including backtests, metrics, or any strategy output — is a recommendation
  to buy or sell anything. Backtested and simulated results are hypothetical and do not
  predict future performance.
- **The strategies are yours.** You choose them, configure them, and decide when they
  run. The Service does not decide what to trade; it does what your strategy tells it.

A separate **live-trading Terms variant is scaffolded for a future v0.2** and is **not
in force**. It does not apply to anything you do today. If and when live trading is
enabled, it will ship as its own versioned document with its own acceptance step, and
you will be asked to accept it before any real-money feature is unlocked.

## 3. Your responsibilities

Because the Service acts on your instructions with your broker, a few things are on you:

- **Your broker keys.** You supply your own brokerage API credentials. We store them
  encrypted at rest, but you are responsible for keeping them valid, for what they
  authorize, and for revoking them at your broker if your account is compromised.
- **Your strategies and alerts.** You own and are responsible for the strategy logic
  and the webhook alerts you send. If your alert says "buy," the Service will try to
  buy (in paper). Review your own strategies; we don't vet them for you.
- **Your credentials.** Keep your password and your webhook secret private, keep MFA
  enabled, and don't paste secrets into places they don't belong. Tell us promptly if
  you suspect unauthorized access.
- **Compliance.** You are responsible for using the Service in line with the laws that
  apply to you and with your broker's own terms.

## 4. Acceptable use

Don't use the Service to:

- break the law, or violate your broker's or any market's rules;
- attack, overload, probe, or reverse-engineer the Service, or bypass its rate limits,
  authentication, webhook `sig` secret, or kill-switch controls;
- send alerts or content that are fraudulent, malicious, or manipulative (including
  attempts at market manipulation, even in simulation);
- access another user's data, account, strategies, orders, or audit records;
- upload malware, or use the Service to build a competing product by scraping it.

We run automated safeguards (rate limits, idempotency checks, per-user and
platform-wide kill switches). Don't try to defeat them.

## 5. No warranty; limitation of liability

**The Service is provided "as is" and "as available," without warranties of any kind**,
express or implied, including merchantability, fitness for a particular purpose, and
non-infringement. We do not warrant that the Service will be uninterrupted, error-free,
or that any strategy will execute at a particular time, price, or at all.

**Trading involves risk.** Even in paper mode the Service is a tool, not a fiduciary,
not an adviser, and not a guarantee. It may miss an alert, submit late, retry, or halt
your strategies (for example when a kill switch trips). Simulated results can differ
sharply from any real market. You are solely responsible for your trading decisions and
their outcomes.

**To the maximum extent permitted by law**, StratTraderPro and its operators are not
liable for any indirect, incidental, special, consequential, or exemplary damages, or
for any lost profits, lost or simulated trading gains, or data loss, arising out of or
relating to your use of the Service. Because the Service is currently paper-only and
provided at no charge for beta, our total aggregate liability to you is limited to the
greater of the amount you paid us in the 12 months before the claim (which is currently
zero) or USD 100. Some jurisdictions don't allow certain exclusions, so parts of this
section may not apply to you.

## 6. Intellectual property

- **Ours:** the Service — its software, design, and content (excluding your data) — is
  owned by StratTraderPro and its licensors. These Terms don't transfer any of that to
  you beyond the right to use the Service as described here.
- **Yours:** you keep ownership of your strategies, your configurations, and the data
  you put in. You grant us only the limited license needed to operate the Service for
  you — to store, process, and act on that content so the Service can function.

## 7. Termination & your deletion right

- **You can leave any time.** You can request account deletion in the app. Deletion is
  a **30-day soft delete**: your account is scheduled for removal 30 days out, and you
  can cancel any time within that window (the app confirms by email). At the end of the
  window a scheduled job anonymizes your personal data in place. To preserve the
  integrity of our append-only audit trail, an **anonymized stub** of past audit records
  is retained — those records no longer identify you.
- **Your data, before you go.** You can request a personal-data export (profile,
  strategies, orders, fills, backtests, and your own audit events) delivered as a ZIP
  via a time-limited download link. Broker credentials and MFA secrets are redacted from
  the export.
- **We can terminate too.** We may suspend or end your access if you materially breach
  these Terms, create risk for the Service or other users, or if we stop offering the
  Service. Where practical we'll give notice.
- Sections that by their nature should survive — §5 (no warranty / liability), §6 (IP),
  and this survival clause — continue after termination.

## 8. Changes to these Terms

We may update these Terms. When we do, we publish a new **version** and set a new
effective date. Material changes take effect on **re-acceptance**: the next time you
sign in after a version bump, the app shows a blocking prompt and you must accept the
current version before continuing. We record which version you accepted, when, and from
what IP. If you don't accept, you can still export or delete your data, but you won't be
able to keep using the trading features.

## 9. Contact

Questions about these Terms: **legal@strattraderpro.com** (address TBD — the domain is
not yet provisioned; see M11 §7.9). Until then, reach the maintainer through the project
repository.

---

*Draft authored under M11 §7.8 to support the acceptance flow. Not legal advice.
Supersede this file with the counsel-reviewed version before the effective date is set,
and bump the version line when you do.*
