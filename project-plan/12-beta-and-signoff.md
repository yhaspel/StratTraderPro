# Milestone 12 — Private Beta, Bugfix & MVP Signoff

> **Week:** 12
> **Duration:** 5 working days
> **Depends on:** M11
> **Unlocks:** v0.1.0 production tag → post-MVP roadmap (live-trading, marketplace, etc.)

## 1. Purpose

Run a private beta with 3–5 trusted users in paper mode, collect feedback, fix the top-priority issues, and formally sign off the MVP against the §1.1 success criteria in the master plan. No new scope. The deliverable is a production release (`v0.1.0`) that can onboard new users safely.

## 2. In Scope

- Inviting 3–5 beta users (friends / early prospects).
- Dedicated beta communications channel (Telegram group + mailto).
- Daily triage of beta feedback; ticket creation + prioritization.
- Fix critical (P0/P1) bugs; park P2/P3 in backlog.
- Polish obvious UX papercuts found during beta.
- Final demo script rerun verifying all §1.1 success criteria.
- Release notes, changelog, and marketing-shell page (static).
- Final production deploy of `v0.1.0`.
- Post-MVP roadmap doc capturing all parked items.

## 3. Out of Scope

- Major new features (any new scope idea → post-MVP backlog).
- Live trading enablement (v0.2).
- Mobile app (v0.2).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-12-1 | 3–5 beta users onboarded; each completes registration + MFA + broker (paper) connection. |
| AC-12-2 | Each beta user successfully fires at least one TradingView webhook and sees a paper fill. |
| AC-12-3 | Each beta user configures their risk profile and fires a kill switch at least once (drill). |
| AC-12-4 | All §1.1 MVP success criteria (from master plan) independently verified; each has a dated evidence row in `/docs/mvp-signoff.md`. |
| AC-12-5 | All P0 bugs from beta feedback fixed and verified; all P1 either fixed or explicitly deferred with rationale. |
| AC-12-6 | 24-hour soak test post-deploy shows no unresolved alerts; SLO error budget intact. |
| AC-12-7 | Release `v0.1.0` tagged and deployed to prod; rollback tested in staging as a fire drill. |
| AC-12-8 | Post-MVP roadmap committed with prioritized items, ADR placeholders, and rough effort estimates. |
| AC-12-9 | User-facing help center has at least 8 articles covering: register/MFA, connect broker, upload strategy, set TradingView alert, risk profile, kill switch, backtest, troubleshoot. |

## 5. Definition of Done

Baseline DoD applies, plus:

- Beta sign-off email sent to each user confirming move from beta to general paper-trading.
- On-call rotation active from prod-launch date.
- `v0.1.0` release notes published.
- Yuval's own account is MFA-enabled and actively running the platform for dogfood.

## 6. Implementation Tasks

### 6.1 Beta kickoff

- Identify 3–5 users; send invitations with a short onboarding doc.
- Send each a unique signup link + pre-configured strategy to reduce onboarding friction.
- Schedule a 30-minute onboarding call with each (if geography allows); otherwise async help.
- Create a beta-only Telegram group for feedback.

### 6.2 Daily ops cadence (Mon–Fri)

- **09:00:** Check dashboards, alerts, overnight errors in Sentry.
- **10:00:** Beta group messages triaged → GitHub issues tagged `beta`.
- **12:00–15:00:** Fix critical issues; ship small changes.
- **17:00:** Daily summary post in beta group; tomorrow's plan.
- **18:00:** Run smoke test harness against staging + prod.

### 6.3 Bug bar

- **P0:** security, data integrity, kill switch ineffective, money-movement bug (n/a in paper but still guard), auth broken — **fix same-day**.
- **P1:** broken primary flow (can't place order, can't see position) — **fix within 24h**.
- **P2:** degraded secondary flow, UI glitch — fix if time; otherwise triaged to v0.2 backlog.
- **P3:** polish / nice-to-have — backlog.

### 6.4 Feedback instrumentation

- Ship a tiny "Give feedback" button on dashboard → opens a Sentry user-feedback widget OR a Telegram link.
- Aggregate beta-tag Sentry errors into a dedicated Grafana panel.

### 6.5 Release process

- Cut `v0.1.0-rc.2`, `rc.3`, etc. as needed.
- When bar met: cut `v0.1.0` → protected deploy → 24h soak → close.
- Update `CHANGELOG.md` with complete v0.1.0 release notes.
- Tag master plan doc with "MVP delivered" annotation.

### 6.6 Help center

Write / polish 8 help articles in `frontend/src/assets/help/`:
1. Create your account + MFA.
2. Connect your paper broker (Alpaca).
3. Connect your paper broker (TradeStation — if the M05 second-broker scope shipped).
4. Upload a strategy (the 3 files).
5. Set up a TradingView alert.
6. Understand your risk profile.
7. Use the kill switch.
8. Run a backtest.

### 6.7 Post-MVP roadmap

`/docs/post-mvp-roadmap.md`:
- Priority 1: Live trading rollout (separate ADR + legal; 4–6 weeks).
- Priority 2: Alpaca + Schwab adapters (2 weeks each).
- Priority 3: Options Greeks-aware sizing (3 weeks).
- Priority 4: Strategy marketplace / community-tested promotion.
- Priority 5: Mobile-friendly responsive polish → native wrapper (TBD).
- Priority 6: GPU LLM worker migration when Tier-2 volume > 500/day.
- Priority 7: Per-symbol regime classifier.
- Priority 8: Portfolio-level risk (VaR, correlation caps).

Each entry has: 1-line summary, success criteria, rough effort, dependencies.

### 6.8 MVP signoff doc

`/docs/mvp-signoff.md` with a table for each §1.1 criterion:
| # | Criterion | Evidence | Verified by | Date |
|---|---|---|---|---|
| 1 | ... | PR link, Playwright run id | Yuval | 2026-07-07 |
| 2 | ... | ... | ... | ... |

Doc is signed with a final "MVP delivered" commit.

## 7. Tech Stack Notes

No new tech. All activity in M12 is operational.

## 8. Data Model Changes

None expected. Any schema change this week is an indication the bug bar is being violated — escalate.

## 9. API Contract Changes

None expected. Breaking changes this late are a red flag.

## 10. Test Plan

### 10.1 Regression

- Full existing Playwright + integration + unit suite must stay green.
- Staging deploy of every RC triggers a smoke test.
- Prod deploy of `v0.1.0` triggers canary smoke test.

### 10.2 Acceptance re-verification

- Every §1.1 criterion exercised by a scripted test AND a manual walkthrough recorded as a short screen capture.

### 10.3 Beta usage test

- Each beta user's first-hour experience is observed (over call or review of session replay if consented).

### 10.4 Post-launch soak

- 24h soak post-prod deploy: no new P0/P1 errors; SLO error budgets intact.

## 11. Security Considerations

- Beta users undergo the same MFA + terms-acceptance flow; no shortcuts.
- Access to prod admin limited to Yuval; backup admin contact noted in on-call doc.
- Sensitive info shared with beta users (broker connection steps) delivered via StratTraderPro UI, not over chat.

## 12. Observability

- Dedicated "Beta" Grafana dashboard filtering errors/events to beta users.
- Alert thresholds tightened during beta (e.g., any auth error on beta user pages pages immediately).

## 13. Translation & Localization

- MVP ships in `en` only, but all translation scaffolding is in place (per cross-cutting conventions in README).
- Help center articles written with translation-friendly structure (short paragraphs, no idioms, no culture-specific examples).
- A single post-MVP task budgeted for adding `es` (Spanish) as the first additional locale — not delivered in M12.

## 14. Documentation Deliverables

- `/docs/mvp-signoff.md`.
- `/docs/post-mvp-roadmap.md`.
- `/CHANGELOG.md` — v0.1.0 release notes.
- `frontend/src/assets/help/` — 8 help articles.
- Runbook `/docs/runbooks/beta-support.md`.

## 15. Rollback Plan

- `v0.1.0` deploys via the same GitHub Actions pipeline; rollback = revert to `v0.11.x-rc` tag; tested as a drill in §6.5.
- If a post-launch P0 surfaces, revert and announce within 30 min.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| Beta users uncover a major design flaw late | Med | High | Keep a 10% buffer in Week 12 for rework; escalate to tech-debt post-MVP if unfixable. |
| Solo dev burnout after 12-week sprint | High | Med | Explicit break window (2 weeks) before starting v0.2. |
| Beta users want live trading immediately | High | Med | Clear messaging: paper is the MVP; live = v0.2 on a quality bar. |
| Legal review of ToS slips | Med | Med | Minimum-viable ToS ready; upgrade when counsel responds; legal-review ADR tracks. |

## 17. Exit Gate Checklist

- [ ] AC-12-1 … AC-12-9 pass.
- [ ] `v0.1.0` tag deployed to prod; 24h soak clean.
- [ ] MVP signoff doc committed and signed.
- [ ] Post-MVP roadmap committed.
- [ ] Release notes published.
- [ ] Help center articles published.
- [ ] Beta users migrated onto production normal paper-trading (or graduated).
- [ ] On-call rotation active.
- [ ] Announcement (internal or soft-public) sent.

**MVP delivered.** 🎯
