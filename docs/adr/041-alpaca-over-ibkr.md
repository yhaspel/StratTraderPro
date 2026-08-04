# ADR-041 — Alpaca Trading API replaces IBKR as the M04 execution broker

**Date:** 2026-07-05
**Status:** Accepted
**Milestone:** M04 — Webhook Ingest & Broker Adapter (rescoped)
**Supersedes:** the IBKR execution path of ADR-040 (gateway sidecar) and the entire M04A sub-milestone (archived at `project-plan/archived/04A-IBKR-Web-API.md`)

## Context

M04's broker layer was planned in two steps: ship fast on IB Gateway (TWS
Socket API, ADR-040), then migrate to IBKR's Client Portal Web API with
OAuth (M04A) as the durable multi-user transport.

Both steps hit account-side walls that we do not control:

1. **The M04A OAuth path is blocked.** The account is held via Interactive
   Israel (IBKR's Israeli introducing entity), and the IBKR Web API
   consumer/application approval required by `04A-IBKR-Web-API.md` §5.1
   never cleared. The approval clock (5–10 business days, quoted) is
   IBKR-side and has no workaround for this account type.
2. **The Gateway path works but is operationally hostile.** The 2026-05-15
   spike close-out (ADR-040 Findings) proved orders fill, and also proved:
   paper accounts silently drop headless TWS-API access after ~5–6 days
   without a web-portal login (weekly manual re-auth forever), and
   `gnzsnz/ib-gateway:10.45.1e` allows exactly one TWS-API session per
   process boot (container-per-session orchestration). Acceptable as a
   bridge to M04A; unacceptable as the destination now that M04A is gone.

With the durable IBKR path unreachable, continuing to build M04 Phase B on
the Gateway would invest production code in a transport we already decided
was interim.

## Decision

**Alpaca (Trading API v2) becomes the first execution broker.** M04
Phase B+ ships on `AlpacaAdapter`; all IBKR execution work is parked.

Key properties (verified 2026-07-05):

- **No application/consumer approval gate.** Any Alpaca user can generate
  API keys from the dashboard. Paper trading is free for all users — the
  exact failure mode that blocked both IBKR paths does not exist.
- **Pure REST + WebSocket.** No Java sidecar, no IBC, no GUI automation,
  no per-process session limit, no dormancy re-auth loop. The entire
  ADR-040 gotcha catalogue becomes irrelevant.
- **First-party SDK:** `alpaca-py` (0.43.4, 2026-04-29, Apache-2.0,
  Python ≥3.8 — compatible with our 3.12). `TradingClient(paper=True)`
  against `https://paper-api.alpaca.markets`; `TradingStream` websocket
  delivers `trade_updates` (order acks, fills, cancels).
- **Multi-user story is credential-per-user, not process-per-user.** Each
  user pastes their own paper API key pair; rows are Fernet-encrypted with
  the existing platform KEK (same pattern as MFA + webhook secrets).
  Alpaca also offers an OAuth "Connect with Alpaca" program and a Broker
  API for fully embedded accounts — both are approval-gated, so they are
  explicitly *later* options, not MVP dependencies.
- **Rate limits:** Trading API ~200 requests/min per account (429 on
  breach) — far above MVP alert volume; retry-with-jitter still required.
- **Market data:** free Basic plan includes real-time IEX + 15-min-delayed
  SIP; Algo Trader Plus (paid) unlocks full SIP. Relevant to M06 (a free
  equities-bars source now exists alongside FMP), not to M04.

## Consequences

- `project-plan/04-webhook-ingest-and-ibkr.md` is rewritten around
  `AlpacaAdapter` (filename kept for link stability; title updated).
  The M04A spec is moved to `project-plan/archived/04A-IBKR-Web-API.md`
  with a SCRAPPED banner (scrapped plans live in `project-plan/archived/`).
- The `BrokerAdapter` protocol (M04 §6.1) is **unchanged** — this pivot
  swaps the first concrete implementation, exactly the swap M04A was
  designed to prove cheap. TradeStation (M05) slots in unchanged later.
- IBKR artifacts are **parked, not deleted**: `docker/ib-gateway/`,
  ADR-040, `docs/runbooks/ib-gateway-reauth.md`, and
  `scripts/spike_ibkr_smoke.py` stay in-tree as a working reference. The
  compose service moves behind an opt-in profile so `make up` no longer
  boots it. `TWS_USERID`/`TWS_PASSWORD` leave `.env.example`, and the
  IBKR credentials should be rotated once the envs are scrubbed
  (carried over from 04A's AC-04A-12c).
- **Open item (owner: Yuval):** Alpaca *live* account eligibility for
  Israeli tax residents must be confirmed with Alpaca support before any
  live-trading milestone (M12+). Paper trading — everything the MVP needs
  — carries no such dependency. Non-US live onboarding exists (KYC via
  their international flow, funding from $1), but country eligibility is
  not publicly enumerated.
- Position/fill semantics differ from IBKR in ways M04 must encode:
  Alpaca is US equities/ETFs (+ options, crypto) only, `client_order_id`
  gives us idempotent submits, and `close_all_positions(cancel_orders=True)`
  is a native one-call flatten — which simplifies the M08 kill-switch
  contract.

## Alternatives considered

1. **Persist with IB Gateway as the destination** — rejected: weekly
   manual re-auth and one-session-per-boot are not a professional-grade
   operational posture, and multi-user requires container-per-user.
2. **Wait out / retry IBKR Web API approval** — rejected: unbounded
   timeline, already failed once for this account type; the milestone
   cannot be hostage to it.
3. **TradeStation first (promote M05)** — rejected: also
   approval/account-gated, no official Python SDK, and it would leave the
   webhook→fill pipeline unproven while we built a from-scratch client.
4. **Alpaca Broker API (embedded sub-accounts)** — rejected for MVP:
   approval-gated partnership track; the Trading API with per-user keys
   proves the product first.
