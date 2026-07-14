# M14 — Frontend first paint (prerendered app shell)

> **Depends on:** nothing. Purely frontend + serving layer. Can run in parallel with the M11 tail,
> M12 and M13.
> **Unlocks:** AC-11-12 (FCP ≤ 1.2 s on throttled 4G), which M11 measured and **missed**.
> **Status:** SPEC. Not started.
> **Created:** 2026-07-13

---

## 1. The problem, measured

Lighthouse, production, mobile, genuine Slow-4G simulation (`rttMs 150`,
`throughputKbps 1638.4`, `cpuSlowdownMultiplier 4`):

| Metric | Value | Target |
|---|---|---|
| **FCP** | **2.8 s** | ≤ **1.2 s** → **MISS (2.3×)** |
| LCP | 3.7 s | — |
| Speed Index | 2.8 s | — |
| TBT | **90 ms** | — |
| Perf score | 84 | — |
| Initial bundle | 473.28 kB | < 520 kB gate ✅ |

## 2. Read the numbers before proposing a fix

The instinct is "473 kB is big, shrink the bundle." **The data says that is the wrong lever.**

- **TBT is 90 ms.** If parsing/executing JS were the bottleneck this would be in the many hundreds.
  The CPU is fine. This is **not** an execution problem.
- **The bundle is already under budget** (473 of 520 kB). It is not a regression.
- **FCP 2.8 s and LCP 3.7 s are only ~0.9 s apart.** FCP and LCP arriving almost together is the
  signature of *nothing rendering at all until the app boots, then everything at once*.

That is the actual diagnosis: **StratTraderPro is a client-rendered SPA.** The browser receives an
essentially empty `<app-root></app-root>` and **cannot paint a single pixel** until it has fetched
the JS, parsed it, bootstrapped Angular and rendered the first component. FCP is therefore floored by
`round-trip + boot`, no matter how tidy the bundle is.

### The arithmetic that kills the "just shrink it" plan

Slow-4G = 204.8 kB/s, 150 ms RTT. Even after M11's compression work
(initial payload **144.3 kB** gzip-9 → ~0.72 s of pure transfer), you still pay:

```
  DNS + TCP + TLS + HTML            ~0.3–0.5 s   (before one byte of JS moves)
+ JS transfer                        ~0.72 s
+ parse + bootstrap + first render   ~0.5–1.0 s   (cpuSlowdown 4x)
                                     ──────────
                                     ~1.5–2.2 s   ...and that is the FLOOR for CSR.
```

Halving the bundle again buys perhaps 0.35 s. **You cannot shrink your way from 2.8 s to 1.2 s from
a pure CSR app.** The only change that structurally decouples first paint from the JS round-trip is
to **ship real HTML**.

## 3. Already done in M11 (do not redo)

These landed as the "cheap wins" and are **not** part of M14:

- **gzip was serving at level 1** (nginx's default — nothing overrode it). Fixed: assets are now
  pre-compressed at **gzip -9** at image build and served via `gzip_static` (best ratio, zero
  per-request CPU), with `gzip_vary` pinned. Initial payload **168.2 kB → 144.3 kB (~0.12 s)**.
- **`/config.js` was a render-blocking classic script in `<head>`** — the parser stopped and waited a
  full RTT for 326 bytes before it could paint. Now `defer`red (~0.15 s+).
- **Brotli: measured and REJECTED.** brotli-11 (128.2 kB) beats gzip-9 (144.3 kB) by only ~0.08 s,
  and the official nginx image ships no `ngx_brotli` — adopting it means replacing the base image and
  losing the upstream entrypoint's `envsubst` step, which is load-bearing and CI-guarded (BUG-004:
  a broken `NGINX_ENVSUBST_FILTER` served the SPA a literal `"${SENTRY_DSN}"` and Sentry silently
  no-op'd for weeks). **Trading that for 80 ms is a bad deal.** Revisit only if M14 replaces the base
  image anyway (§5, option B).
- **`modulepreload` + font inlining**: already emitted by the Angular production builder. Nothing to do.

Expected post-M11 FCP: **~2.5 s**. Still ~2× the target. Hence M14.

## 4. Goal

**FCP ≤ 1.2 s on the Slow-4G mobile profile**, on the routes an unauthenticated visitor can actually
reach. Everything else is secondary.

## 5. Approach — prerender the shell (decision required)

Angular 19 supports prerendering (SSG) via `@angular/ssr` without running a Node server in
production: `ng build` emits static HTML per route, which nginx serves directly.

### Option A — Prerender the public routes only (RECOMMENDED)

Prerender exactly the routes reachable without auth: `/` (landing), `/login`, `/register`,
`/help/*`, `404`. Output is plain static HTML; nginx serves it; Angular hydrates on top.

- **Pros:** no Node runtime in prod (Railway topology unchanged — still one nginx container); no
  new services; the routes that dominate first-impression traffic paint immediately.
- **Cons:** authenticated routes (`/dashboard`, …) are still CSR — but those are *behind a login*,
  are not measured by the AC, and their users are warm-cached.
- **Risk:** low. The build gets slower; the serving layer barely changes.

### Option B — Full SSR (`@angular/ssr` with a Node server)

- **Pros:** authenticated routes get server-rendered too.
- **Cons:** adds a **Node process in production** — a new Railway service, a new `SERVICE_ROLE`,
  new failure modes, and it must be added to the M11 §7.0 entrypoint dispatch. It also puts a
  render path in front of every request, with the DB/auth latency that implies.
- **Risk:** meaningful. This is a topology change to a platform that is about to trade real money.

**Recommendation: Option A.** It hits the AC, keeps the "Railway-native, zero new services" posture
(M12 locked decision 2), and avoids putting a Node renderer on the critical path of a trading app.
Revisit B only if authenticated-route paint becomes a real complaint.

## 6. Scope

- `@angular/ssr` added; `ng build` configured to **prerender** the public route list (Option A).
- A real **app shell** in the prerendered HTML: header, nav skeleton, and a content skeleton — so the
  first paint is *meaningful*, not a blank frame with a spinner.
- Hydration enabled (`provideClientHydration()`), so Angular adopts the server HTML instead of
  destroying and re-creating the DOM (which would cause a visible flash and re-layout).
- `runtime-config.ts` must keep working: `/config.js` is injected by **nginx at request time**, but
  prerendered HTML is generated at **build time** — these must not be conflated (see §8, trap 1).
- CI: a Lighthouse assertion so FCP cannot silently regress again.

## 7. Out of scope

- Full SSR / a Node server in production (Option B).
- Brotli — unless the base image is replaced for another reason.
- Bundle-size work. It is not the bottleneck (§2). Do not let it in through the back door.
- Any change to authenticated-route rendering.

## 8. Traps — read before writing code

1. **Runtime config vs build-time prerender.** `window.STP_CONFIG` is produced by **nginx envsubst at
   container start** (`/config.js`), and it differs per environment. Prerendered HTML is baked at
   **image build**. If any prerendered component reads `STP_CONFIG` *during prerender*, it will bake
   the **build-time** value (empty!) into the HTML and ship it to every environment. The prerendered
   shell must not depend on runtime config at all — and there should be a test that proves it.
   *This is BUG-004's exact shape: config that looks substituted but isn't.*

2. **Hydration mismatch = a worse experience than CSR.** If the prerendered DOM and the client's
   first render disagree, Angular tears the DOM down and rebuilds it — you get a flash, layout
   shift, and a **worse** CLS/LCP than before. Any `Date.now()`, `Math.random()`, `window`/
   `localStorage` access, or auth-dependent branch in a prerendered component will do this. Audit
   `ShellComponent` and the landing page specifically.

3. **Do not prerender authenticated routes.** They would bake a logged-out shell into static HTML
   and serve it to logged-in users.

4. **The nginx SPA fallback must not swallow the prerendered files.** Today `location /` is
   `try_files $uri $uri/ /index.html`. With prerendering there is a real `/login/index.html` on disk;
   the fallback must serve *that*, not the generic shell, or the whole milestone is a no-op that
   still "works". **Verify by fetching `/login` and grepping the response for rendered markup —
   not by trusting that the build emitted the file.**

5. **`gzip_static` must cover the new HTML.** The M11 precompress step already globs `*.html`, so
   prerendered routes get `.gz` for free — but confirm, don't assume.

## 9. Acceptance criteria

| # | AC | Kind |
|---|---|---|
| AC-14-1 | `curl -s <prod>/login` returns HTML containing **rendered app markup** (not just `<app-root></app-root>`). Asserted on the response body, not on the presence of a build artifact. | CI |
| AC-14-2 | Lighthouse mobile / Slow-4G on `/` reports **FCP ≤ 1.2 s**. | CI (assert) |
| AC-14-3 | LCP ≤ 2.5 s and **CLS ≤ 0.1** on the same run — proving hydration did not introduce a re-layout (trap 2). | CI (assert) |
| AC-14-4 | Zero hydration errors (`NG0500`/`NG0501`) in the console on `/`, `/login`, `/register`, `/help/*`. | CI (e2e) |
| AC-14-5 | The prerendered HTML contains **no** environment-specific value — no backend URL, no Sentry DSN, no literal `${...}`. Grep the built artifact. (trap 1) | CI |
| AC-14-6 | An authenticated route (`/dashboard`) is **not** prerendered — no static HTML for it in `dist`. | CI |
| AC-14-7 | A Lighthouse CI budget fails the build if FCP regresses above 1.2 s. **Without this, M14 rots the moment someone adds a render-blocking tag.** | CI |
| AC-14-8 | `check_envsubst_filter.py` still passes and `/config.js` still returns the substituted runtime config. | CI |

## 10. Definition of done

- FCP measured ≤ 1.2 s on prod, Slow-4G mobile, and the number is recorded in the perf ticket
  alongside the 2.8 s "before".
- AC-14-7 is green — the target is now **enforced**, not merely achieved once. A perf target with no
  CI gate is a number in a document; it will regress within a month.

## 11. If the target is wrong, say so

Worth asking before spending the effort: **≤ 1.2 s FCP on Slow-4G was written before anyone
measured.** This is an authenticated trading dashboard for a handful of beta users, not a public
content site where FCP drives bounce and SEO. Slow-4G is a punitive profile for that audience.

If Option A lands at, say, 1.4 s, the correct response may well be to **amend the AC with evidence**
rather than to keep spending. What is *not* acceptable is quietly leaving a target in the plan that
the product misses by 2× and nobody re-measures — that is how AC-11-12 got here.
