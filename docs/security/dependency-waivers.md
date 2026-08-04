# Dependency audit — waivers & Dependabot triage (M11 §7.2 / AC-11-1)

**Last reviewed:** 2026-07-12

Two CI gates guard dependencies, and they gate **differently**:

- **`pip-audit`** (backend) has **no severity threshold** — it fails on *any* known
  advisory. The only suppression is `--ignore-vuln <ID>`. So the Python gate is
  **"zero un-waived advisories"**, and every ignored ID is a row below.
- **osv-scanner + `scripts/audit-gate.mjs`** (frontend) filters by severity — the Node gate is
  **"zero un-waived HIGH+"**. (npm retired its audit endpoints (HTTP 410), which broke
  `pnpm audit`; osv-scanner reads `pnpm-lock.yaml` against OSV.dev instead. Waivers are still the
  same `pnpm.auditConfig.ignoreGhsas` list in `package.json`.)

CI command (backend):

```
pip-audit -r requirements/base.txt -r requirements/prod.txt \
  --ignore-vuln PYSEC-2025-110 --ignore-vuln PYSEC-2025-111 \
  --ignore-vuln PYSEC-2026-56  --ignore-vuln CVE-2026-49452
```

## Resolved by upgrade (not waived) — M11 §7.2

| Package | 0.10.x pin | New pin | Advisory cleared | Why it applied |
|---|---|---|---|---|
| `djangorestframework` | `>=3.14,<3.15` | `>=3.15.2,<3.16` | PYSEC-2026-1304 (XSS in `break_long_headers`) | DRF ships the vulnerable template filter |
| `djangorestframework-simplejwt` | `>=5.3,<5.4` | `>=5.5.1,<5.6` | PYSEC-2026-1305 (disabled user keeps a live access token) | **directly relevant** to the M11 GDPR delete/anonymize flow |
| `daphne` | `>=4.1,<4.2` | `>=4.2.2,<4.3` | PYSEC-2026-213 (unbounded WS frame/message → DoS), PYSEC-2026-214 (header smuggling) | the public `/ws/dashboard/` is served by daphne |

All three verified compatible: full backend suite **586 passed, 0 failed** after the bump.

## Waivers (pip-audit `--ignore-vuln`)

| ID | Package | Fix exists? | Why waived | Revisit by |
|---|---|---|---|---|
| PYSEC-2025-111 | django-allauth 0.61.1 | 65.13.0 | **Not applicable.** The flaw is Okta/NetIQ using `preferred_username` as the account identifier. We enable **only the Google provider** (`SOCIALACCOUNT_PROVIDERS` = `google`) — no Okta/NetIQ. | allauth major upgrade (below) |
| PYSEC-2025-110 | django-allauth 0.61.1 | 65.13.0 | **Not applicable.** The flaw is allauth acting as an **IdP** (its own tokens not rejected after `is_active=False`). We use allauth as an OAuth **consumer** of Google, never as an IdP; the IdP app is not enabled. | allauth major upgrade |
| PYSEC-2026-56 | django-allauth 0.61.1 | 65.14.1 | **Not applicable.** Open redirect via **SAML IdP-initiated SSO**, which is **disabled by default** and not enabled here (no SAML provider). | allauth major upgrade |
| CVE-2026-49452 | weasyprint 68.1 | **none** | **Not applicable + no fix.** CSS injection when processing **untrusted HTML** with presentational hints. WeasyPrint renders **only our own first-party Django templates** (M09 tearsheets) — no untrusted HTML reaches it. No patched version exists. | when a weasyprint fix ships |

### Why django-allauth is waived, not upgraded

The "fix" is a **0.61 → 65.x major jump**. allauth removed the old-style settings this
codebase depends on (`ACCOUNT_AUTHENTICATION_METHOD`, `ACCOUNT_EMAIL_REQUIRED`,
`ACCOUNT_USERNAME_REQUIRED`, …) in favour of `LOGIN_METHODS`/`SIGNUP_FIELDS`, and changed
the adapter API (`apps/users/social_adapters.py`). Upgrading is a **feature-scope change**
that would break the Google OAuth flow and require live-Google re-testing — explicitly out
of M11 (hardening, not features). All three advisories are **demonstrably not applicable** to
our single-provider consumer configuration, so waiving with this rationale is safe. The
allauth major upgrade is tracked as dedicated follow-up work.

## Frontend — osv-scanner HIGH+ gate (`pnpm.auditConfig.ignoreGhsas` in `package.json`)

**Resolved by upgrade:** `@angular/*` bumped **19.2.21 → 19.2.25** (the latest 19.2.x),
clearing **GHSA-p3vc-36g9-x9gr** (Number-format DoS) and **GHSA-q6f4-qqrg-jv6x**
(credentialed-response default caching info-leak), both patched in `>=19.2.23`.
`pnpm install --frozen-lockfile` stays clean; `pnpm build` unaffected.

**Waived HIGH+ (20), two categories:**

*Category 1 — `@angular` framework, patched only in Angular 20+ (`patched=<0.0.0` in 19.x), and N/A to this client-only SPA:*

| GHSA | What | Why N/A here |
|---|---|---|
| GHSA-39pv-4j6c-2g6v | Weak 32-bit cache key in `HttpTransferCache` | Transfer cache is an **SSR** feature; this app has **no `@angular/ssr`, no `platform-server`, no `provideClientHydration`** (verified by grep). Not active. |
| GHSA-rgjc-h3x7-9mwg | Client **hydration** DOM clobbering / response-cache poisoning | Same — no SSR/hydration in this SPA. Not active. |
| GHSA-48r7-hpm6-gfxm | DatePipe OOM DoS via attacker-controlled **format string** | All date formats are **static literals** in templates; no user input is passed as a format string. |

These three are only fixed in Angular 20+; a two-major upgrade is out of a hardening PR
(feature-scope, build-breaking) and tracked with Dependabot **#9** (deferred). Revisit at the
Angular 21 toolchain upgrade.

*Category 2 — dev/build-tooling transitive deps, NOT present in the shipped SPA bundle:*
`shell-quote` (GHSA-w7jw-789q-3m8p, critical), `tar` (×6), `ws`, `tmp`, `vite`, `piscina`,
`serialize-javascript`, `sigstore`, `fast-uri` (×2), `http-proxy-middleware`,
`websocket-driver` (GHSA-xv26-6w52-cph6, critical — HTTP-parser DoS; only `sockjs@0.3.24` ⇒
`webpack-dev-server`/`karma` pull it, and there is no patched 0.7.x release, so `ng build`'s
compiled bundle contains none of it and only a dev machine running the test/serve tooling
could be targeted), `@babel/plugin-transform-modules-systemjs`. All are transitive deps of
`@angular/cli` / `@angular-devkit/build-angular` / `karma` / `webpack-dev-server` — build- and
test-time only.
The compiled bundle (`ng build`) contains none of them, so they are not a runtime attack
surface for end users. `pnpm overrides` were considered but rejected for a hardening PR
(forcing a dozen deep toolchain deps risks destabilising the build for zero shipped-code
benefit); the real fix is the deferred Angular 21 toolchain upgrade (Dependabot #9). Revisit
at that upgrade.

*Category 2 addendum — 2026-07-25 (review-remediation integration):* the osv-scanner
advisory database added 11 new GHSA IDs (16 advisory rows across versions) since these
branches were cut, all for the **same build/test-time transitive dev tooling** already
covered above — no dependency was added or changed (the `pnpm-lock.yaml` is byte-identical to
`main`). Waived for the same reason (build-/test-time only, absent from the `ng build`
bundle), so `main` too would fail this gate until they are listed:
`brace-expansion` (GHSA-3jxr-9vmj-r5cp, GHSA-mh99-v99m-4gvg — via `glob` in the toolchain),
`fast-uri` (GHSA-4c8g-83qw-93j6, GHSA-v2hh-gcrm-f6hx — via `ajv` schema validation),
`immutable` (GHSA-v56q-mh7h-f735, GHSA-xvcm-6775-5m9r — `@angular/build`),
`js-yaml` (GHSA-52cp-r559-cp3m — config tooling),
`postcss` (GHSA-r28c-9q8g-f849 — dev CSS pipeline / Tailwind),
`shell-quote` (GHSA-395f-4hp3-45gv — dev server),
`tar` (GHSA-23hp-3jrh-7fpw *critical*, GHSA-8x88-c5mf-7j5w — `@angular/cli` extraction).
None appear in the shipped SPA; the real fix remains the deferred Angular 21 toolchain
upgrade (Dependabot #9).

*Addendum — 2026-08-04 (M16 integration):* six more IDs, again with **no dependency change**
(`pnpm-lock.yaml` and `package.json` dependency sets are byte-identical to the ones `main` was
green on).  The gate had been green on this exact lockfile at 05:37Z on 2026-08-03 and was red
by ~23:00Z the same day, so `main`, PR #52 and every open branch failed it simultaneously — the
advisory database moved, the repository did not.  One of the six (`ip-address`) appeared during
the ~2h of this integration alone, which is the reason this list is re-checked at each merge
rather than trusted.

Four are the familiar **Category 2** (build/test-time transitive, absent from the `ng build`
bundle), and the dependency path was traced with `pnpm why` in each case rather than assumed:

| GHSA | Package | Path (`pnpm why`) | Why N/A |
|---|---|---|---|
| GHSA-rgw5-rvv9-x895 | `brace-expansion` 1.1.14 / 2.1.0 | `minimatch` → `glob` → `karma`/`rimraf`; `minimatch` → `@redocly/openapi-core` → `openapi-typescript` | Test runner + the OpenAPI type generator. Explicitly supersedes the already-waived GHSA-3jxr-9vmj-r5cp / GHSA-mh99-v99m-4gvg (it bypasses their mitigation), same package, same reasoning. |
| GHSA-7p8r-x3mc-p8w7 | `fast-uri` 3.1.0 | `ajv` → `@angular-devkit/core` / `schema-utils` | Build-time JSON-schema validation of `angular.json`. Third sibling on this package after GHSA-4c8g-83qw-93j6 / GHSA-v2hh-gcrm-f6hx. |
| GHSA-mwp4-54f8-5fhr | `ip-address` 10.2.0 | `socks` → `socks-proxy-agent` → `@npmcli/agent` | npm's own network agent — only reachable while *installing* packages, never in the SPA. |
| GHSA-2m8v-j782-fhvr | `socket.io-parser` 4.2.6 | `socket.io` → `karma` | The karma dev server's browser channel; test-time only. |

Two touch packages that **are** shipped (`@angular/common`, `@angular/core`,
`@angular/compiler`), so they get feature-level justification rather than a
not-in-the-bundle argument:

| GHSA | What | Why N/A here (verified, not assumed) |
|---|---|---|
| GHSA-jhpw-976m-542j | Cache-key ambiguity in `HttpTransferCache` → cross-request response reuse | Third advisory on the **SSR-only** transfer cache after the already-waived GHSA-39pv-4j6c-2g6v / GHSA-rgjc-h3x7-9mwg. Re-verified on this tree: `provideClientHydration`, `@angular/ssr`, `platform-server`, `TransferCache` and `TransferState` return **0 hits** across `src/`, `package.json` and `angular.json`. The feature cannot be switched on. |
| GHSA-jj27-h5hq-8x99 | Angular **i18n**: XSS via event-handler attributes in translated messages | The app localises with **ngx-translate**, not Angular's built-in i18n. `@angular/localize` is **not a dependency at all** (`pnpm why` finds nothing; no `localize`/`ssr` entry in `package.json`). Decisively: the i18n runtime marker `ɵɵi18n` appears in **0 of the 72 built bundle files**, so no i18n instruction is compiled into the app and the vulnerable path is unreachable. The single `$localize` occurrence in the bundle is Angular's defensive `typeof $localize < "u" && $localize.locale` guard in the `LOCALE_ID` factory, which resolves to the default locale precisely because the runtime is absent. |

The two Angular entries are fixed only in 20.3.27+ / 21.2.19+ — the same two-major upgrade
already deferred as Dependabot **#9**, and still the real fix. Revisit at that upgrade.

## Dependabot triage (13 open PRs, counted 2026-07-12)

The freeze-time estimate of "~5" was low. Disposition of each:

| PR | Bump | Disposition | Rationale |
|---|---|---|---|
| #1 | actions/setup-python 5→6 | **Safe to merge** | Action major bump, no behavior change for our usage. |
| #2 | actions/cache 4→5 | **Safe to merge** | Cache action, backward-compatible. |
| #3 | actions/checkout 4→6 | **Safe to merge** | Checkout action; our steps use defaults. |
| #4 | nginx 1.27→1.29-alpine (frontend image) | **Safe to merge** | Patch stream; clears base-image CVEs; the envsubst guard still holds. |
| #5 | node 20→25-alpine (docker) | **Defer** | CI pins Node 20 (`.github/workflows/ci.yml`); bumping the image without the CI toolchain diverges local/CI. Revisit with a coordinated Node upgrade. |
| #6 | python 3.12→3.14-slim (docker) | **Defer** | CI pins Python 3.12; several pinned wheels (hmmlearn, vectorbt tree) have no 3.14 wheels yet. |
| #9 | @angular/cli 19→21 | **Defer** | Angular **two-major** jump; a build-breaking change well outside a hardening PR (M12 freezes deps). |
| #12 | python-json-logger <2.1→<4.2 | **Defer (breaking)** | 3.x moved the import path (`pythonjsonlogger.jsonlogger` → `pythonjsonlogger.json`); `config/settings/base.py` LOGGING references the old path. Needs a code change + retest. |
| #13 | uvicorn 0.27→0.46 | **Defer / low-value** | uvicorn is unused at runtime (prod = gunicorn WSGI, ws = daphne). Big jump for a dep on no hot path; drop it in a cleanup PR instead. |
| #14 | celery-redbeat <2.2→<2.4 | **Safe-ish, defer to a focused PR** | Beat scheduler; low risk but beat is a live control path — bump + re-run the beat→queue→worker loop deliberately, not bundled into M11. |
| #15 | bandit <1.8→<1.10 | **Safe to merge** | Dev-only linter; range widening. |
| #16 | sentry-sdk <2.0→<3.0 | **Defer (sensitive)** | The WSGI revert (`docker/backend.Dockerfile`) exists partly because of sentry 1.x↔ASGI behavior; a 2.x jump needs deliberate testing of the Django+Celery integrations. Not in a hardening PR. |
| #21 | minor-and-patch group, 5 updates | **Review then merge** | Grouped low-risk patch bumps; safe to merge once CI is green on it. |

**Net:** the security-relevant Python advisories are resolved in M11 directly (DRF, simplejwt,
daphne bumps above) rather than via the Dependabot PRs. The **safe-to-merge** Action/image PRs
(#1–#4, #15, #21) can be merged by the operator; the **deferred** ones (#5, #6, #9, #12, #13,
#14, #16) each carry a reason above and are tracked. None blocks the M11 gates.

### Re-triage 2026-08-04 — ⚠️ the table above is partly WRONG, do not act on it

Every one of the 15 open PRs was re-checked against `main` at `b4aadc9`. Two findings invalidate
the "safe to merge" column wholesale:

1. **None of these PRs has a green CI run.** They are stale-**red**, from 2026-04-18, ~119 commits
   behind, and their logs have expired (HTTP 410), so the failure cause is unrecoverable. The
   2026-07-12 dispositions were judgements about the *diff*, never evidence that CI passed.
2. **Nothing can land until `main`'s two dependency-audit gates are green.** Branch protection is
   `strict: true` and requires `Backend — Lint & Test` + `Frontend — Build & Test`; both were red
   on `main` (osv-scanner HIGH+ and pip-audit). Because `strict: true` forces an update-to-main
   first, re-running any of these PRs makes it *inherit* those red gates — so a re-run proves
   nothing about the bump itself. Dependabot's auto-rebase is also off for PRs open >30 days, so
   they will not self-update.

Corrections to specific rows, each verified in the tree rather than inferred:

| PR | 2026-07-12 said | Actually |
|---|---|---|
| #3 | Safe to merge | **Cannot merge.** It edits `.github/workflows/deploy-staging.yml`, deleted by the OSS pivot (`d52ab7c`, PR #34, 2026-07-15) — *three days after* this table was written. Modify/delete conflict. It also bumps only 4 of the 10 `actions/checkout@v4` sites now on `main`, so it would half-migrate the tree. |
| #4 | "Patch stream" | **Wrong.** 1.27 → 1.29 crosses two nginx mainline minors and skips the 1.28 stable branch. The PR's target is itself now stale. |
| #1, #2 | Safe to merge | Substance still fine (v6/v5's only breaking change is the Node 24 runtime; every job is GitHub-hosted `ubuntu-latest`, no `container:` jobs). But coverage drifted — `loadtest-canary.yml` (added by PR #32, after this table) also pins `setup-python@v5`, so #1 no longer covers the tree. Land #1+#2 as one Actions PR that includes it. Note `actions/cache` v4→v5 moves to a new cache service: the first run after merge is a cold cache, slower but not a failure. |
| #21 | "Merge once CI is green on it" | **Its own precondition has failed** — its green is a snapshot of the last minute before the OSV database moved. It also touches `pnpm-lock.yaml`, which interacts with the `ignoreGhsas` list above: a lockfile change can make waived IDs stop matching or surface new ones, so it needs a fresh osv run, not its old one. |
| #15 | "Dev-only linter" | Conclusion right, **reasoning wrong**: CI runs `bandit … --severity-level medium` as a hard gate in the Backend job, so a newly-added detector in a wider range can fail the build. Still the one genuine merge candidate. |

Rows that were verified and **still hold**, with the reason now confirmed rather than assumed:
**#5** (CI pins Node 20 in two jobs *and* `docker-compose.yml` runs `node:20-alpine`),
**#6** (CI pins Python 3.12 — the image would run a different interpreter than CI tests),
**#9** (`CONFLICTING`/`DIRTY`, 79 commits behind),
**#12** (`config/settings/base.py:815` still references `pythonjsonlogger.jsonlogger`),
**#13** (the only non-requirements mention of uvicorn in the repo is a *commented-out* line in
`docker/backend.Dockerfile:84`),
**#14** (`CELERY_BEAT_SCHEDULER = "redbeat.RedBeatScheduler"` is live and byte-pinned in
`docker/entrypoint.sh`),
**#16** (the WSGI-hotfix comment in `docker/backend.Dockerfile:70-86` is still in force).

**Nothing was closed.** All 15 remain wanted upgrades blocked on sequencing, not irrelevant —
and closing a Dependabot PR suppresses future re-offers of that version, which would lose the
Angular 21 signal (#9) we actually want.

**Operational note:** `.github/dependabot.yml` caps the `github-actions` ecosystem at
`open-pull-requests-limit: 3`, and #1/#2/#3 consume all three — so no new Action bump, *including
a security-driven one*, can be opened until those are resolved.
