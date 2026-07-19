# One-shot prompt for Claude Code — StratTraderPro design-system implementation

Copy everything below the line into Claude Code, run from the repo root, with the handoff bundle unzipped at `design_handoff/`.

---

Implement the new "Industry" design system across the StratTraderPro Angular frontend, replacing the current drifted Tailwind styling. This is a **visual-layer migration only** — no behavior, routing, state, facade, API, or i18n-key changes.

## Read first (in this order)
1. `design_handoff/README.md` — scope, fidelity, screen-by-screen spec
2. `design_handoff/angular-migration-notes.md` — the implementation map: token CSS, component mapping, status→color table, screen notes
3. `design_handoff/_ds/industry-*/readme.md` + `styles.css` — the design system's own rules and token sheet
4. The three `design_handoff/*.dc.html` mockups — visual ground truth (view source for exact values; they are HTML prototypes to RECREATE in Angular, never code to copy)

## Hard rules
- Never hard-code a hex, font name, or px value that a token carries — everything through CSS custom properties mapped into Tailwind.
- Green/red are reserved for money and risk semantics ONLY; the steel accent is for actions/focus/progress/equity; every status keeps a text label (never color-only).
- Do not add ANY new actionable element (no buttons, links, or menus that don't map to an existing handler). Keep TradeStation connect and LIVE mode disabled-with-reason exactly as they are.
- Keep all existing a11y behavior: role=alert, aria-busy, focus-trapped modals, skip link, keyboard row activation. WCAG AA; accent at body-text size uses `--color-accent-700`.
- Blueprint grammar: cards/panels/dialogs are square-cornered, transparent, hairline-bordered with four "+" corner registration marks; the solid accent primary button is the one filled object.
- All numerics/ids/hashes/JSON in IBM Plex Mono with `tabular-nums`, right-aligned in tables, signs always displayed; neutral band |x| ≤ 0.05 renders muted.
- Preserve every i18n key; do not hard-code strings.
- Run `make test-fe` (or `pnpm test`) after each phase; fix regressions before moving on.

## Phase 1 — Token layer
1. Replace `frontend/src/styles/tokens.css` with the Industry tokens: port `:root` variables from `design_handoff/_ds/industry-*/styles.css` (colors + 100–900 ramps, fonts, spacing, radius, shadows) PLUS the trading-semantics extension block from `angular-migration-notes.md` §1 (up/down/warn/bear + tints/deeps, regime palette, `--font-mono`).
2. Update `frontend/tailwind.config.js` to map the new variables (accent, neutral ramp, up/down/warn/bear + tints/deeps, regime-*, font-heading/body/mono, space, radius 0/sm/md, shadows) the same way the current vars are mapped.
3. In `frontend/src/index.html`, replace the Inter/JetBrains Mono Google Fonts link with `Barlow:wght@400;500;700`, `Barlow+Condensed:wght@400;600`, `IBM+Plex+Mono:wght@400;500;600`.
4. Update `frontend/src/styles.scss`: body background `var(--color-bg)`, color `var(--color-text)`, `font-family var(--font-body)`; headings `var(--font-heading)`; global `:focus-visible` 2px accent ring; themed `::selection`.

## Phase 2 — Shared UI kit (`frontend/src/app/features/shared/ui/`)
Restyle/extend per `angular-migration-notes.md` §2:
1. `button.component.ts` — variants primary (solid accent), secondary (hairline), ghost, danger (solid `--down`), success (solid `--up`; used ONLY for Release actions). Square corners, Barlow Condensed 600 14px, disabled 45% opacity, keep the loading spinner + aria-busy.
2. `card.component.ts` — blueprint panel: transparent, 1px `--color-divider`, radius 0, four corner registration marks (implement the marks as a reusable pattern — a directive or a small wrapper component — so every framed surface shares it).
3. `modal.component.ts` — blueprint dialog on `--color-bg` with `--shadow-lg`; destructive dialogs: `--down` title + danger primary. Keep focus trap + `dismissable`.
4. `page-header.component.ts` — h2 32px Barlow Condensed 600, muted 14px subtitle, actions slot.
5. `empty-state.component.ts` — dashed `--color-neutral-400` frame, transparent, Barlow Condensed heading.
6. `toast-host.component.ts` — white card, hairline border, 3px semantic left edge (up/down/accent), `--shadow-md`.
7. NEW `status-chip.component.ts` — one chip (tint background + deep text, 11px 700): implement the full mapping from notes §3 (order, backtest, broker stream w/ square dot, regime, badges SYSTEM/USER/PAPER/DEFAULT/AUTO). Replace every ad-hoc `bg-*-100 text-*-800` span in orders/backtest/brokers/risk/strategies with it.
8. NEW `toggle.component.ts` — 40×20 square toggle, track `--up` when on / `--color-surface` off, square knob; extract from strategies-list.
9. NEW `drawer.component.ts` — 440px right panel on `--color-bg`, left hairline, `--shadow-lg`, focus management; extract from orders.
10. `totp-input.component.ts` — 6 square boxes 44×54 on `--color-surface`, mono 22px, 2px accent border on the active box.

## Phase 3 — Shell + screens
Migrate each to the new kit per README "Screens / Views" and notes §4, matching the mockups:
1. `shared/shell/shell.component.ts` — light header w/ bottom hairline, framed bar-chart logomark + wordmark (accent "Pro"), nav links with 2px accent underline on active, Live dot, user menu. MOVE the halt banner above the header here (it currently lives inside dashboard only).
2. `features/dashboard/` (+ sentiment-panel, regime-badge, regime-history) — layout and colors per mockup; sentiment number sign-colored; regime band uses `--regime-*`.
3. `features/orders/` — filter toolbar card, dense table (36px rows, 13px, mono right-aligned), status chips, drawer component.
4. `features/strategies/list/` + `webhook-config-modal` — tags, toggle, ghost actions; dialog per mockup (rotate = danger-tinted with warning line).
5. `features/backtest/` launcher + detail — form per mockup; chart colors: equity `--color-accent-700`, drawdown `--down` w/ 18% fill, window bars sign-colored, heatmap diverging through the surface color at zero; PBO > 0.5 red + "⚠ high".
6. `features/risk/` — profile grid w/ mono inputs + help text, kill-switch card (red border when armed), inline MFA confirm pattern (input + danger confirm + secondary cancel — identical markup order everywhere).
7. `features/settings/brokers/` + `profile` + `security` + `mfa-setup` — per mockup; keep LIVE + TradeStation disabled with their honest notes.
8. `features/admin/` — sub-nav, KPI cards, kill-switch card, typed-confirm halt dialog + inline-TOTP release.
9. `features/landing/` + `features/auth/*` + `shared/onboarding/` + `not-found` + `help` — per the auth mockup; centered 400px blueprint card, Google secondary button, blueprint-framed primary submit.

## Phase 4 — Sweep + verify
1. Grep and eliminate every remaining raw Tailwind palette usage (`blue-600`, `gray-*`, `red-600`, `green-*`, `amber-*`, `slate-*`) in `frontend/src/app/` — everything goes through the new tokens/components.
2. Run frontend tests + the a11y e2e specs; fix breakage (many specs assert classes — update assertions to the new classes, not the behavior).
3. Boot the stack and visually diff each screen against the corresponding mockup section; list any intentional deviations at the end.

Report at the end: files changed per phase, test status, remaining raw-color usages (should be zero), and any spec ambiguities you resolved with your own judgment.
