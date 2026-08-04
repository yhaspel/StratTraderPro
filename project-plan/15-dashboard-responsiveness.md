# M15 — Dashboard responsiveness (perceived performance + installable PWA)

> **Depends on:** nothing hard. **Sequence after M14** — they share the nginx serving layer, and the
> service worker should precache M14's prerendered public shells too. Purely frontend + serving layer.
> **Unlocks:** the "top-notch, fast dashboard" goal that M14 explicitly does *not* deliver — M14
> speeds up the *login* screen; this speeds up the screen you live in.
> **Status:** SPEC. Not started.
> **Created:** 2026-07-14 (OSS pivot — deferred dashboard-speed work; see `PIVOT-TO-OSS.md`).

---

## 1. The problem — what M14 leaves on the table

M14 prerenders the **public** routes (landing, login, help) and, by its own §7, changes **nothing**
about authenticated-route rendering. So the dashboard — `frontend/src/app/features/dashboard/dashboard.component.ts`,
where you and every self-hoster actually spend time — still has two felt problems:

1. **Every visit pays the full cold CSR boot.** No prerender, no cache — `bootstrapApplication`
   (`frontend/src/main.ts:29`), blank `<app-root>` until the JS round-trip completes. There is no
   repeat-load win: the fifth time you open your dashboard is as slow as the first.
2. **Once booted, the dashboard pops and jumps.** Loading is a single `<p>{{ 'common.loading' }}</p>`
   (`dashboard.component.ts:121-122`) replaced by a multi-row positions table — a real vertical
   layout shift. Some panels (fills at `:162`, broker status at `:93`) have **no** loading guard at
   all and flash empty→data. And the one mutation you can make — halt my trading — waits a full
   server round-trip with **no pending feedback** before anything visibly changes
   (`risk.facade.ts:101-115`, re-fetch at `:110`).

Neither is a first-paint problem (M14's domain). Both are **perceived-performance** and
**repeat-load** problems, which need different levers.

## 2. Measure first — this has NOT been measured

M14 earned its plan by leading with a measured miss (FCP 2.8 s). **M15 has no baseline yet — do not
guess.** Before writing code, capture, on the *authenticated* dashboard under a realistic profile
(not Slow-4G — the real audience is you and self-hosters on a laptop or home connection):

| Metric | What it measures | "Good" threshold |
|---|---|---|
| **INP** (Interaction to Next Paint) | responsiveness — the Core Web Vital that replaced FID | ≤ 200 ms |
| **CLS** | layout jump as data arrives | ≤ 0.1 |
| **Repeat-load time** | second visit, warm cache — the PWA win | (baseline first) |
| **Time-to-first-meaningful-data** | REST snapshot → first painted row | (baseline first) |

Set targets **from** the baseline (§9). A number written before measuring is how AC-11-12 (the FCP
miss) happened.

**How these get measured — the harness does not exist in the repo yet.** `frontend/package.json` has
**no Lighthouse / LHCI** dependency, so the perf-assertion harness is an unbuilt **shared
prerequisite** with M14 (AC-14-7) — establish it once before either milestone can gate. The e2e
harness that *does* exist is **Playwright** (`@playwright/test`, `tsconfig.e2e.json`) with
**`@axe-core/playwright`** for accessibility. One correctness note: **INP is a *field* metric** — a
synthetic run cannot produce a real INP. In CI, measure a **scripted interaction-to-next-paint** via
Playwright's Event Timing API, and/or gate on **TBT** as the lab proxy; reserve true INP for optional
real-user monitoring. **CLS is** lab-measurable directly. Pin the throttle for the gates (e.g. CPU
4×, warm cache, no network throttle for the authenticated case) so the numbers are reproducible.

## 3. The two levers

### Lever A — In-app perceived performance (client-side, no server)

- **Skeleton screens.** There is **no skeleton component today** (`grep skeleton|shimmer` → 0). Add
  `app-skeleton` to the shared UI kit (`frontend/src/app/features/shared/ui/` — alongside the
  existing `card`, `empty-state`, `spinner`, `modal`, `toast/`). Size each skeleton to its eventual
  table so it **reserves space** → zero CLS.
- **Wire the panels that don't gate on loading.** Fills (`dashboard.component.ts:162`) and broker
  status (`:93`) don't read `facade.loading()` — they need new gating or they'll keep flashing
  empty→data behind a skeleton that never shows.
- **Preserve and extend the 3-way state.** Positions/fills/brokers already branch
  `loading → MFA-gated → empty → data` (`:124-128`, `:163-167`) — good foundation. But regime
  (`regime-badge.component.ts:89`) and sentiment (`sentiment-panel.component.ts:74-75`) wrongly show
  a generic `no_data` when the real cause is the **MFA 403**. Extend the three-state model to them;
  a skeleton must not paper over the honest "enable 2FA to use this" state.
- **Instant route transitions.** The shell already stays mounted — `<router-outlet>` lives inside
  `ShellComponent` (`frontend/src/app/features/shared/shell/shell.component.ts:150-152`), so nav
  swaps only the outlet. But feature routes are lazy (`app.routes.ts`) with **no transition
  indicator** (`grep NavigationStart` → 0): first visit to a route is blank until the chunk resolves.
  Add a route-transition affordance (top-bar progress or a skeleton), and consider
  `withViewTransitions()` on `provideRouter` (`app.config.ts:25`).
- **Optimistic UI on the halt.** The kill-switch/halt is the **only** UI mutation surface — orders
  are read-only (`orders.api.ts` is all GETs). `RiskFacade.triggerHalt/releaseHalt` returns a
  `Result<T>` ok/error union already (`risk.facade.ts:13,73-79`). Today it awaits the server, then
  re-fetches, then the banner appears — buttons have no pending state (`dashboard.component.ts:223`).
  Make it optimistic: immediate "requesting halt…" affordance, reconcile on ack, roll back loudly on
  failure. **Caveat: optimistic ≠ fabricated — see trap 3.**

### Lever B — Service worker / installable PWA (frontend-only, no new server)

Confirmed greenfield in *code*: no `ngsw-config.json`, no `manifest.webmanifest`, no
`provideServiceWorker()` anywhere (`grep ngsw|webmanifest` → 0). `@angular/service-worker` is not a
direct dependency, but it already resolves as an optional peer in `pnpm-lock.yaml` — so adding it is
a first-party, version-matched install: pin `@angular/service-worker@^19.2.x` to match Angular
19.2.25 (`frontend/package.json:20-27`).

- **Precache the app shell.** `@angular/service-worker` (ngsw) precaches the content-hashed JS/CSS/
  `index.html` (`angular.json` `outputHashing: "all"`, `outputPath: dist/strattraderpro/browser/`) →
  **instant repeat-load** and installability.
- **Web app manifest** — installable, home-screen icon. Genuinely valuable for a dashboard you check
  on your phone.
- **No Node server.** That's M14 Option B, rejected. This is frontend-only and self-host-friendly:
  it adds no process, no `SERVICE_ROLE`, nothing to the entrypoint dispatch.

## 4. THE CENTRAL CONSTRAINT — never serve stale money data

This is M15's equivalent of M14's runtime-config trap, and it is **more dangerous**: M14's trap ships
an empty config; this one could show someone a **stale position, P&L, or "no halt" banner as if it
were live**, and they might act on it. Treat it as a correctness requirement, not a perf tuning knob.

- **The service worker precaches the STATIC SHELL ONLY** — hashed JS/CSS/`index.html`/assets.
  **Everything under `/api/*` is `NetworkOnly`.** No `freshness` or `performance` data groups on any
  authed endpoint. This is also a **security** rule: caching an authed response risks serving one
  user's positions to another on a shared device (refresh token is in `localStorage`, access token
  in-memory — `auth.store.ts:5,10`). Token/refresh endpoints and `/config.js`: also `NetworkOnly`.
- **The WebSocket is the source of truth for live data** (`ws.service.ts`; positions/fills/broker
  frames via `dashboard.facade.ts:70-88`). Today, on disconnect, positions/P&L **freeze on screen
  showing their last values** with only a gray "offline" dot (`dashboard.component.ts:50-55`). M15
  must add an explicit **stale state** — last-updated timestamp, stale badge, or dimmed values — so
  "frozen" is never mistaken for "current." (AC-15-7.)
- **The halt banner is a latent correctness bug this milestone should fix.** It is populated only by
  one-shot REST on mount (`dashboard.component.ts:268` → `risk.store.ts:29`), and the WebSocket
  **never carries halt/kill-switch events** (`grep halt` in `ws.service.ts` → 0). So a **platform/
  admin halt, or a server-side auto-halt triggered elsewhere, will not appear until the next
  navigation.** M15 must (a) never cache-serve it, and (b) **move halt/kill-switch onto the WS
  stream** so it is real-time. Safety state that can be up to a full session stale is the last thing
  you want behind a cache layer.

## 5. Out of scope

- **SSR / a Node server** (M14 Option B).
- **Offline *trading*.** You cannot place or cancel orders offline. When offline the app must **fail
  clearly** — a visible "you're offline; data may be stale; actions are disabled" state — and must
  **never** queue trades or present cached data as actionable. The PWA is for instant repeat-load and
  install, full stop.
- **First cold paint of authenticated routes.** The SW speeds up *repeat* loads; the very first cold
  paint is still floored by the JS round-trip (no SSR — by design).
- **Bundle-size work** (M14 §2 — not the bottleneck).
- **Prerendering authenticated routes** (M14 §7).

## 6. Traps — read before writing code

1. **Stale money data** — the whole of §4. The one that turns a perf feature into a correctness bug.
2. **SW self-update vs nginx's immutable rule.** The static-asset `location` in
   `docker/nginx.conf.template:94-97` sends `Cache-Control: public, immutable` for a year — and its
   regex would match **`ngsw-worker.js`**, freezing the service worker so it can never update. Add an
   explicit `location = /ngsw-worker.js { add_header Cache-Control "no-cache"; }` (and `safety-worker.js`).
   `index.html` is already `no-store` (`:47`) — correct for the update model. Ship an update prompt
   (skipWaiting + a "new version — reload" toast via the existing `ToastService`) so a self-hoster's
   redeploy lands cleanly.
3. **Optimistic UI must never fabricate a financial outcome.** Optimistic = an immediate *pending*
   affordance ("requesting halt…", a disabled+spinner button), reconciled on server ack. It must
   **never** show an order as filled or a halt as *active* before confirmation. The halt is
   safety-critical: if the request fails, say so **loudly** (a toast + a persistent error), because a
   user who thinks they halted and didn't is worse off than one who sees the request is still pending.
4. **Cross-origin fonts cause CLS *and* break offline.** Inter + JetBrains Mono load from Google
   Fonts with `display=swap` (`index.html:9-11`) → a font-swap layout shift, and ngsw won't precache
   cross-origin fonts without a data group. **Self-host both fonts** — kills the CLS and closes the
   offline-font gap in one move.
5. **Skeleton ≠ empty ≠ not-configured.** Keep the honest three-way split (§3). A skeleton is for
   *loading*; the MFA-gated and empty states are not loading and must stay distinct.
6. **Auth + SW.** Never cache authed responses or token endpoints; **logout must clear SW caches**
   (AC-15-12) or the next user on the device could recover data.
7. **iOS PWA limits.** Install UX differs; storage can be evicted. Set expectations; don't rely on
   the SW cache surviving indefinitely.

## 7. Acceptance criteria

| # | AC | Kind |
|---|---|---|
| AC-15-1 | Baseline INP / CLS / repeat-load captured and recorded **before** any change. | perf ticket |
| AC-15-2 | Dashboard interaction latency ≤ 200 ms, measured as a **scripted interaction-to-next-paint** (Playwright Event Timing) — *not* a Lighthouse "INP", which is field-only; **TBT ≤ 200 ms** may serve as the lab proxy. Target confirmed from baseline (§9). | CI (Playwright) |
| AC-15-3 | Dashboard **CLS ≤ 0.1** on load — skeletons reserve space, fonts self-hosted. | CI (assert) |
| AC-15-4 | Every data panel shows a **skeleton** while loading and preserves the **loading / MFA-gated / empty** three-way distinction — including regime + sentiment (which don't today). | CI (e2e) |
| AC-15-5 | Service worker precaches the app shell; **second load serves the shell from cache** (offline → shell paints; online → data loads). | CI (e2e) |
| AC-15-6 | **Freshness proof:** with the SW active and network blocked, positions/orders/fills/halt show the **stale/offline** state, **not** cached values presented as live. An automated test asserts `/api/*` is `NetworkOnly`. | CI |
| AC-15-7 | On WS disconnect the dashboard shows an **explicit stale / last-updated** state, not frozen-looking-live. | CI (e2e) |
| AC-15-8 | Halt / kill-switch state is **never cache-served** and is delivered over the **WebSocket in real time** (no longer mount-only REST). | CI (e2e) |
| AC-15-9 | **Installable:** valid `manifest.webmanifest`, app installs, launches to the dashboard. | manual + CI lint |
| AC-15-10 | **SW update flow:** a new deploy invalidates the old shell (`ngsw-worker.js` not immutable-cached); the user gets an update prompt / clean reload. | CI (e2e) |
| AC-15-11 | **Optimistic halt:** button shows pending immediately, confirms on ack, surfaces failure loudly, and **never** shows halt active before ack. | CI (e2e) |
| AC-15-12 | **Logout clears SW caches;** no authed data recoverable from cache afterward. | CI (e2e) |

*"CI (e2e)" = Playwright (`@playwright/test`). "CI (Playwright)" / "CI (assert)" depend on the perf
harness prerequisite in §2. "CI lint" = manifest / ngsw-config validation. None of the perf gates
can be claimed green until that harness exists.*

## 8. Definition of done

- Baseline **and** after numbers recorded in the perf ticket, side by side.
- INP + CLS **gated in CI** (AC-15-2/3). A target with no gate regresses within a month — the
  AC-11-12 lesson, again.
- The freshness proof (AC-15-6) is **automated, not eyeballed** — it is the one that protects real
  decisions, so it cannot be a manual spot-check.

## 9. If the target is wrong, say so

Mirror M14 §11. INP ≤ 200 ms and CLS ≤ 0.1 are the Core Web Vitals "good" thresholds — written for
the general web, not measured against this app. For a single-user, self-hosted dashboard, **repeat-
load and installability** may matter more to the felt experience than shaving a specific INP number.
Set the numeric targets from the §2 baseline and **amend with evidence** rather than chase a figure
that doesn't change how it feels.

What is **not** negotiable, and not a "target" you may relax: the §4 freshness guarantees. Shipping
the service worker without AC-15-6/15-7/15-8 is not a slower dashboard — it is a dashboard that can
lie about money. If Lever B can't meet those, ship Lever A alone and defer B.

## 10. Sequencing

- **After M14** (shares the serving layer; the SW should precache M14's prerendered public shells)
  and **after the OSS release is out** — this is polish, not a release blocker.
- **Lever A and Lever B are independent.** A (skeletons, CLS, optimistic halt, stale indicator) is
  lower-risk and delivers most of the "feels fast" win — land it first. B (the PWA) carries the
  freshness risk and must not ship until AC-15-6 is proven green.
- The **halt-over-WebSocket** change (§4, AC-15-8) is a real-time correctness improvement that stands
  on its own merit — if M15 slips, consider pulling that one item forward independently.

## 11. i18n

Every new user-facing string goes through `@ngx-translate` into `frontend/src/assets/i18n/en.json`
— no hard-coded text (the `ngc --noEmit` template check and the repo DoD both enforce it). Strings
this milestone adds, at least: `dashboard.stale` / `dashboard.last_updated`,
`dashboard.offline_actions_disabled`, `app.update_available` (+ its reload CTA), `risk.halt_pending`
("requesting halt…"), and an `aria-label` key for the skeleton loading state. For the regime +
sentiment MFA-gated branch (§3), reuse the existing `dashboard.requires_mfa` key or add
`regime.requires_mfa` / `sentiment.requires_mfa` — do **not** overload `*.no_data`.

## 12. Accessibility

`@axe-core/playwright` is a CI gate (WCAG 2.1 AA on touched screens), so a11y is part of *done*:

- **Skeletons:** mark the loading container `aria-busy="true"` and hide the placeholder shapes from
  the a11y tree (`aria-hidden`), so a screen reader announces "busy", not a wall of blank rows.
- **Stale / offline indicator (AC-15-7):** an `aria-live="polite"` region — a silent colour/opacity
  change is invisible to a screen-reader user, which for stale *financial* data is the worst audience
  to leave uninformed.
- **Update-available prompt (AC-15-10):** move focus to the reload control; dismissible by keyboard.
- **Optimistic halt (AC-15-11):** announce the pending → confirmed → failed transitions. The halt
  banner is already `role="alert"` (`dashboard.component.ts:36`) — keep it, and add a status update
  for the pending state.
- Run the axe suite on the dashboard in **both** the skeleton (loading) and loaded states.
