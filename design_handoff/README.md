# Handoff: StratTraderPro Design System Overhaul ("Industry")

## Overview
A complete visual overhaul of the StratTraderPro frontend (Angular 19 + Signals, Tailwind), replacing the drifted blue/gray Tailwind styling with the **Industry** design system — a technical blueprint aesthetic: light ground, one steel-blue accent, Barlow Condensed over Barlow, square corners, hairline frames with "+" registration marks — plus a **trading-semantics extension** (P&L green/red, warning amber, regime palette, mono numerics) that Industry itself does not carry.

The package covers: the design-system reference sheet, redesigned mockups of every key screen (dashboard, orders, strategies, backtest launcher + detail, risk, brokers settings, admin, landing, login, register, MFA), and a file-by-file migration map onto the existing Angular codebase.

## About the Design Files
The `.dc.html` files in this bundle are **design references created in HTML** — interactive prototypes showing intended look and behavior, NOT production code. Open them in a browser (with `support.js` and the `_ds/` folder alongside) to inspect them; view source for exact values. The task is to **recreate these designs inside the existing Angular 19 frontend** (`frontend/src/app/`), using its established patterns: standalone components, Signals, the facade layer, Tailwind mapped to CSS custom properties, and the existing shared UI kit under `features/shared/ui/`. Do not ship the HTML.

## Fidelity
**High-fidelity.** Colors, typography, spacing, chip mappings, and copy are final. Recreate pixel-perfectly using the codebase's existing component architecture. All fixture data (positions, orders, runs) is illustrative only.

## Source of truth, in order
1. `_ds/industry-…/styles.css` — the Industry token sheet + component classes (`.card`, `.blueprint`, `.btn`, `.tag`, `.table`, `.field`, `.input`, `.seg`, `.dialog`, `.nav`). Adopt this (or port its variables into `src/styles/tokens.css` + Tailwind config) verbatim.
2. `_ds/industry-…/readme.md` — the system's own usage rules (blueprint grammar, ramp usage, contrast rules, do/don't).
3. `angular-migration-notes.md` — **the implementation map**: extension tokens (CSS block ready to paste), component-by-component mapping to existing Angular files, the status→color table, screen-level notes, a11y bar, and what was deliberately NOT added.
4. The three `.dc.html` mockups — visual reference for layout, density, and every state.

## Screens / Views
See the mockups; each screen is annotated below with its Angular home.

- **Shell** (`STP App Screens.dc.html`, top) → `features/shared/shell/shell.component.ts`. 54px header on the ground with bottom hairline; framed bar-chart logomark + "StratTraderPro" wordmark (Barlow Condensed 600, accent on "Pro"); nav links with 2px accent underline on active; Live dot (up-green square) + user menu right. Platform/user halt banner renders ABOVE the header (solid `#A63D36`, white Barlow Condensed uppercase).
- **Dashboard** → `features/dashboard/dashboard.component.ts` (+ sentiment-panel, regime-badge, regime-history). Page h2 + danger "Halt my trading" button; MFA-needed amber banner when not enrolled; 2-col: sentiment (mono polarity number colored by sign + sparkline + news list) / regime (BULL tag, degraded chip, 90-day band, broker status chip); positions table; fills list.
- **Orders** → `features/orders/orders.component.ts`. Secondary "Export CSV"; filter toolbar (broker/status/strategy/from/to + primary Apply); dense table (13px, mono right-aligned numerics, status tags); pagination; recon-events panel; row click → 440px right drawer (dl grid + fills + close).
- **Strategies** → `features/strategies/list/…`. Primary "Upload strategy" (blueprint-framed); table with SYSTEM/USER tags, untested amber tag, square toggle (green on), ghost "Configure webhook" / danger-ghost "Delete" (user uploads only). Webhook dialog: URL+Copy, secret hidden w/ Rotate (danger-tinted) + warning, schema + payload textareas (mono), Save / Test payload / Copy TradingView template.
- **Backtest launcher + detail** → `features/backtest/…`. Launcher form (strategy select w/ disabled no-adapter option, symbols, dates, train/test/step-readonly, mode/metric/cash, sizing segmented, param-grid JSON textarea, advanced `<details>`, blueprint-framed submit); runs table with status tags + % + Cancel on active rows. Detail: back link, header (name/symbols/config, COMPLETED tag, Rerun), downloads row (JSON/HTML/PDF secondary buttons + hash), chart tabs (Equity accent-700 line / Drawdown red fill / Monthly diverging heatmap / Per-window sign-colored bars), per-symbol metrics table with PBO > 0.5 flagged red "⚠ high".
- **Risk** → `features/risk/risk.component.ts`. 9 numeric mono inputs (2-col, help text under each), strict-mode checkbox, asset-class chip-select, Save/Reset; kill-switch card (red border when armed; Halt → inline MFA confirm: input + danger confirm + secondary cancel; auto L2 switch row with Release); risk-events feed; sizing-decisions table.
- **Brokers** → `features/settings/brokers/…`. Connected card (PAPER/DEFAULT tags, CONNECTED dot-tag, Test/Remove/Flatten ghost actions, PAPER|LIVE segmented with LIVE disabled + honest tooltip, MFA-gated remove inline); Connect Alpaca form (key/secret/nickname); TradeStation section disabled with feature-flag note.
- **Admin** → `features/admin/…`. Sub-nav (Overview/Users/Audit/Flags/Health); 4 KPI cards (DB, Redis = green OK; queue, backlog = mono numbers); platform kill-switch card — Engage (danger) → typed-confirm dialog (reason + "HALT PLATFORM" phrase + MFA), Release (success green) → inline TOTP.
- **Landing / Login / Register / MFA** (`STP Auth and Landing.dc.html`) → `features/landing/`, `features/auth/…`. Landing: outline tag "SELF-HOSTED · YOU OWN THE KEYS", 56px h1, blueprint-framed primary CTA, 4 numbered how-it-works cards, disclaimer. Auth: centered 400px blueprint card, Google button (secondary w/ logo), OR divider, fields, disabled-until-valid submit. MFA: 6 square TOTP boxes (44×54, accent border on focus), backup-code toggle.

## Interactions & Behavior
All in `angular-migration-notes.md` §2/§4 plus visible in the mockups: row→drawer with focus management, dismissable vs blocking dialogs (keep the existing `app-modal` focus trap), inline MFA confirm pattern (identical everywhere), toggle/segmented states, chart-tab switching, disabled-with-reason for TradeStation and LIVE. Motion: 120ms hovers, 200ms overlays, nothing decorative near money. **No new actionable elements were invented** — every button maps to an existing action in the codebase.

## State Management
No new state architecture — reuse the existing facades/stores/Signals. The redesign is presentational plus two structural notes: move the halt banner into the shell, and extract the hand-rolled drawer + toggle + status chip into shared UI components (see notes §2).

## Design Tokens
Industry base: see `_ds/industry-…/styles.css` (`--color-*` incl. 100–900 ramps, `--font-heading/body`, `--space-1…8`, radius 0 on framed objects, `--shadow-sm/md/lg`).
Trading extension (paste-ready CSS in `angular-migration-notes.md` §1):
- up `#2E6B45` / tint `#DFEEE4` / deep `#2E5C40` · down `#A63D36` / `#F6E3E1` / `#8C3A34` · warn `#C9A23E` / `#F3E9D4` / `#6E5220` · bear `#B06A3C` / `#F2E4D8` / `#7A4826`
- regime: bull `#4C8A62`, chop `#C9A23E`, bear `#B06A3C`, crisis `#B3564F`, neutral `#98989b`
- `--font-mono: "IBM Plex Mono"` — all numerics/ids/hashes/JSON, `tabular-nums`, right-aligned, signs always displayed, neutral band |x| ≤ 0.05 muted
- Status→tag mapping table: notes §3. Chips = tint bg + deep text (mirrors `.tag-accent`'s 100/800 pattern). Never color-only — every status keeps its text label.
- Contrast: accent at body size uses `--color-accent-700`; up/down text ≥ 4.5:1 on the ground; WCAG AA throughout.

## Assets
No binary assets. Logomark is inline SVG/divs (framed square + three accent bars) — reproduce from the mockup markup. Fonts from Google Fonts: Barlow, Barlow Condensed (imported by styles.css), IBM Plex Mono (add to `index.html`, replacing Inter/JetBrains Mono). Icons, when needed: Lucide at stroke 1.5 per Industry.

## Files
- `STP Design System.dc.html` — full reference sheet (foundations, extension, type, buttons, forms, status system, tables, banners, overlays, data-viz, nav, principles)
- `STP App Screens.dc.html` — interactive mockups of all authenticated screens (nav switcher, drawer, dialogs, chart tabs work)
- `STP Auth and Landing.dc.html` — landing + auth screens (switcher top-left)
- `angular-migration-notes.md` — implementation map onto `frontend/src/app/` (read this first)
- `_ds/industry-…/styles.css` + `readme.md` — the Industry system itself
- `support.js` — runtime for viewing the `.dc.html` prototypes only; not part of the implementation
