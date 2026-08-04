# StratTraderPro — Design System Handoff Notes

Maps the new design system — the **Industry** system (steel-blue blueprint on a light technical ground, Barlow Condensed/Barlow, square corners, hairline frames with registration marks) plus a **trading-semantics extension** — onto the existing Angular 19 frontend. Grounded in `frontend/src/` at commit `a77667d`. Industry's own tokens/classes live in `_ds/industry-…/styles.css` + `readme.md`; adopt that file as the base stylesheet.

## 1. Token layer — replace `src/styles/tokens.css`

Base = Industry's `styles.css` verbatim (`--color-bg #f2f2f3`, `--color-surface #e9e9ea`, `--color-text #1d1f20`, `--color-accent #5980a6` + full 100–900 OKLCH ramps, `--font-heading` Barlow Condensed / `--font-body` Barlow, `--space-1…8`, radius 0 on framed objects, `--shadow-sm/md/lg`, 2px accent `:focus-visible` ring). Add the app extension:

```css
:root {
  /* Trading-semantics extension — OKLCH-matched to Industry's ramps.
     Steel accent = machinery (actions, focus, progress, equity).
     Green/red = money and risk ONLY; never decorative. */
  --up: #2E6B45;      --up-tint: #DFEEE4;   --up-deep: #2E5C40;   /* profit, fills, connected, OK, release */
  --down: #A63D36;    --down-tint: #F6E3E1; --down-deep: #8C3A34; /* loss, rejected, halt, danger */
  --warn: #C9A23E;    --warn-tint: #F3E9D4; --warn-deep: #6E5220; /* degraded, partial, cancelling, drift */
  --bear: #B06A3C;    --bear-tint: #F2E4D8; --bear-deep: #7A4826; /* regime BEAR only */
  /* info/running/system = the accent itself (accent-100 tint / accent-800 text) */
  --regime-bull: #4C8A62; --regime-chop: #C9A23E; --regime-bear: #B06A3C;
  --regime-crisis: #B3564F; --regime-neutral: #98989b;
  --font-mono: "IBM Plex Mono", monospace; /* all numerics, ids, hashes, JSON */
}
```

Chips = Industry `.tag` with tint background + deep text (mirrors `.tag-accent`'s 100/800 pattern). P&L text on the ground uses `--up`/`--down` (≥ 4.5:1). Accent at body-text size uses `--color-accent-700` per Industry's own contrast rule.

Fonts in `index.html`: swap the Inter/JetBrains link for
`family=Barlow:wght@400;500;700&family=Barlow+Condensed:wght@400;600&family=IBM+Plex+Mono:wght@400;500;600` (Industry's stylesheet already imports the Barlows).

Map tokens in `tailwind.config.js` the same way the current vars are mapped (colors.accent, colors.up, colors.down, etc). Remove raw `blue-600`/`gray-*`/`red-600` usages during migration — that drift is the main defect of the current UI. Blueprint grammar: panels/cards/dialogs are transparent, square, hairline-bordered with the four `+` corner registration marks (`.blueprint` + `<i class="corner tl/tr/bl/br">`); the solid accent primary button is the one filled object.

## 2. Component mapping (shared UI kit)

| System component | File | Changes |
|---|---|---|
| Button (primary / secondary / ghost / danger / success) | `features/shared/ui/button.component.ts` | Industry `.btn` variants; add `danger` (solid `--down`) + `success` (solid `--up`, admin/risk Release only). Primary keeps blueprint marks on hero/submit uses. Keep loading spinner + `disabled:opacity-45`. Square corners. |
| Card / Panel | `ui/card.component.ts` | Industry `.card` + `.blueprint` + 4 corner marks: transparent, hairline `--color-divider`, radius 0. Panel title = h6 overline. |
| PageHeader | `ui/page-header.component.ts` | h2 Barlow Condensed 600 (32px); subtitle 14px muted; actions slot unchanged. |
| Modal | `ui/modal.component.ts` | Industry `.dialog` + blueprint marks on `--color-bg`; destructive dialogs get a `--down` title + danger primary. Keep focus trap + `dismissable`. |
| Drawer (orders detail) | inline in `orders.component.ts` | 440px right panel, `--color-bg`, left hairline, `--shadow-lg`; extract to shared `drawer.component.ts` (currently hand-rolled). |
| Toast host | `ui/toast/toast-host.component.ts` | White card, hairline border, 3px semantic left edge (up/down/accent), `--shadow-md`. |
| EmptyState | `ui/empty-state.component.ts` | Dashed `--color-neutral-400` frame, transparent, heading in Barlow Condensed. |
| Spinner | `ui/spinner.component.ts` | `currentColor` ring, unchanged API. |
| StatusChip (NEW) | create `ui/status-chip.component.ts` | Industry `.tag` (tint bg + deep text) for order/backtest/broker/kill-switch states — see §3. Replaces ad-hoc `bg-*-100 text-*-800` spans in orders/backtest/brokers/risk/strategies. |
| TOTP input | `auth/totp-input/totp-input.component.ts` | 6 square boxes 44×54 on `--color-surface`, mono 22px, 2px accent border on focus. |
| Toggle | inline in `strategies-list.component.ts` | Extract shared toggle; square knob, track `--up` when on / `--color-surface` off; 40×20. |

## 3. Status → color mapping (single source of truth)

- Order: PENDING_SUBMIT neutral (`.tag-neutral`) · SUBMITTED info (accent-100/800) · PARTIAL warn · FILLED up · CANCELLED neutral · REJECTED down
- Backtest: QUEUED neutral · RUNNING info · CANCELLING warn · COMPLETED up · FAILED down · CANCELLED neutral
- Broker stream: CONNECTED up-dot · DEGRADED warn-dot · DOWN down-dot (square dot + label, never color-only)
- Regime: BULL/CHOP/BEAR/CRISIS/NEUTRAL → regime palette above
- P&L / sentiment polarity: `--up` / `--down`, neutral band `--color-neutral-600`; always signed, `--font-mono`, `font-variant-numeric: tabular-nums`
- PBO > 0.5 → `--down` + "high" flag
- Kill switch active → `--down` banner; auto-locked → warn chip; PAPER mode → neutral chip; LIVE → down chip

## 4. Screen-level notes

- **Shell** (`shared/shell/shell.component.ts`): Industry `.nav` on the ground with a bottom hairline; logomark (framed bar-chart mark) + Barlow Condensed wordmark; active nav = accent text + 2px accent underline; keep skip-link, user menu, hamburger. Add halt banner slot ABOVE header (it currently renders inside dashboard only).
- **Dashboard**: KPI strip (equity-style numbers) is NOT added — no backing endpoint; layout = halt banner → MFA notice → sentiment + regime (2-col) → broker status → positions table → fills. "Live/Offline" dot + "Halt my trading" stay in the page header actions.
- **Orders**: filters as one toolbar row; dense table (36px rows, 13px, mono numerics right-aligned); status chips per §3; keep CSV export, pagination, row → drawer.
- **Risk**: profile editor 2-col with mono number inputs; kill-switch card red-tinted when armed; MFA inline confirm pattern (input + danger confirm + ghost cancel) reused from brokers/remove and admin/release.
- **Backtest**: launcher form unchanged functionally; runs table dense; detail = status header + progress bar (accent), chart tabs (accent underline), downloads as secondary buttons; equity line `--color-accent-700`, drawdown `--down` fill, window bars regime-green/red, heatmap diverging through the surface color at zero.
- **Strategies**: table with system/user badge (info/neutral), untested warn banner, toggle, text-button actions (Configure webhook / Delete).
- **Brokers**: TradeStation button stays disabled + honest note (per §7.9 comment). LIVE mode button stays disabled with tooltip.
- **Admin**: KPI cards (db/redis/queue/backlog), halt platform = danger button + typed-confirm modal + TOTP; release = success button + inline TOTP.
- **Auth**: centered 400px card on `--bg`; Google button = secondary w/ logo; landing = dark hero + 4 numbered steps.

## 5. Accessibility (AA)

All text pairs ≥4.5:1 on the ground (up `#2E6B45`, down `#A63D36`, deeps on tints); accent at body size uses `--color-accent-700` (Industry's rule — the raw accent is 3:1, chrome-only); every status carries a text label (never color-only); focus = Industry's 2px accent `:focus-visible` ring; keep existing aria patterns (role=alert on errors, aria-busy on loading buttons, focus traps).

## 6. What was intentionally NOT added

No new actionable elements without backing functionality: no notification bell, no global search, no settings gear, no "new order" button (orders are webhook-driven), no chart range selectors. TradeStation connect and LIVE mode remain disabled-with-explanation as in code.
