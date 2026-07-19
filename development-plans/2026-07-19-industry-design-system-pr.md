# PR: Industry design system migration

Branch: `feat/industry-design-system` (4 commits on top of `main`/a77667d, ready to push)

To open the PR:

```bash
git push -u origin feat/industry-design-system
gh pr create --title "feat(design): migrate frontend to the Industry design system" --body-file development-plans/2026-07-19-industry-design-system-pr.md
```

---

## Summary

Visual-layer migration of the whole Angular frontend to the "Industry" design system (steel-blue blueprint on a light technical ground, Barlow Condensed/Barlow/IBM Plex Mono, square corners, hairline frames with "+" registration marks) plus the trading-semantics extension (up/down/warn/bear, regime palette, mono numerics). No behavior, routing, state, facade, API, or i18n-key changes. Implements `design_handoff/` (README, angular-migration-notes, Industry token sheet, 3 mockups).

## Commits / phases

1. **Token layer** — `tokens.css` replaced with the Industry `:root` variables + trading extension; `tailwind.config.js` maps every var (accent/neutral ramps, up/down/warn/bear + tint/deep, regime-*, fonts, s1–s8 spacing, radius, shadows); fonts swapped to Barlow / Barlow Condensed / IBM Plex Mono; global base (bg/text/headings/focus ring/selection/blueprint CSS) in `styles.scss`.
2. **Shared UI kit** — new `stpBlueprint` directive (square hairline frame + 4 corner marks); button gains ghost/danger/success variants + `frame` input; card/modal/page-header/empty-state/toast/totp restyled; NEW `status-chip` (single source of truth for the notes §3 status→tone mapping incl. broker-stream square dot), NEW `toggle` (40×20 square), NEW `drawer` (440px right panel, extracted from orders, focus-managed).
3. **Screens** — shell (light 54px header, framed logomark, accent-underline nav, halt banner MOVED above the header app-wide), dashboard, orders (+ shared drawer), strategies (list/webhook/detail/upload), backtest launcher + detail (charts read tokens at runtime: equity accent-700, drawdown red 18% fill, diverging heatmap through surface), risk (inline MFA confirm pattern, armed kill-switch treatment), settings (brokers/profile/security/mfa-setup — TradeStation + LIVE stay disabled-with-reason), admin (sub-nav, KPI cards, destructive typed-confirm halt modal, success-green Release), landing + all auth screens (400px blueprint card), help/not-found/onboarding/terms.
4. **AA sweep** — zero raw Tailwind palette classes left in `frontend/src/app`; text-bearing accent fills darkened to `accent-700` and muted text to `neutral-700` after axe flagged raw accent (3.7:1) and neutral-600 (3.8:1) against the ground.

## Verification (run in a Linux sandbox against this branch)

- `ng build` — clean
- `ngc --noEmit -p tsconfig.app.json` — clean (NG5002/NG9 template check)
- `ng test` (Karma/ChromeHeadless) — **129/129**
- `playwright test e2e/a11y` — **5/5** (no critical/serious axe violations on dashboard/orders…admin)
- Raw-palette grep (`blue|gray|red|green|amber|slate|…-N`, `primary-*`, `bg-[#hex]`) — **zero matches** in non-spec app code
- Visual smoke screenshots (mock-API playwright run) of dashboard/orders/backtest/risk/login/landing eyeballed against the mockups

Backend untouched — ruff/bandit/pytest unaffected.

## Intentional deviations from the mockups (with reasons)

1. **Primary buttons & selected segments fill `accent-700`, not raw accent** — raw accent on the ground is 3.7:1; axe (and the CI a11y gate) requires 4.5:1 at 14px. The handoff's own contrast rule ("accent at body size uses accent-700") was applied to filled controls too. Same for the segmented PAPER selection and upload step indicator (active 700 / done 900).
2. **Muted text is `neutral-700`** rather than the mockups' neutral-600 (3.8:1 fails AA for 11–13px labels/nav).
3. **Live dot lives in the shell** (README/mockup) not the dashboard header (notes §4 said "stays") — same `DashboardFacade.connected` signal.
4. **Landing hero stays on the light ground** — the mockup's only dark strip is its design-review switcher, not product UI; notes §4's "dark hero" was judged stale against the mockup.
5. **Mockup page subtitles omitted** where no i18n key exists (no hard-coded strings allowed).
6. **Anchors that look like buttons stay anchors** (upload strategy, enroll-MFA, back-to-login) to preserve link semantics; styled identically to the primary button.
7. **Strategy delete/rotate confirmations remain native `confirm()`** (behavior-preserving; converting to destructive modals would change flow).
8. Five i18n keys added (none changed/removed): `webhook.modal.secret.rotate_warning`, `admin.nav.overview`, `admin.audit.col.hash`, `landing.hero.tag`, `landing.hero.title_pre/_em/_post`.

## Notes for review

- The halt banner is now global (shell) and truthful on every route — shell calls `risk.loadKillswitches()` on init.
- `app-status-chip` exports `STATUS_CHIP_TONE`; ad-hoc `bg-*-100 text-*-800` spans are gone.
- Transient success notices (profile saved, reset-link sent, copied) moved green → accent info tint per "green/red = money and risk only"; broker CONNECTED, FILLED, MFA-enabled, Release stay green deliberately.
