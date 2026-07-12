# Dependency audit — waivers & Dependabot triage (M11 §7.2 / AC-11-1)

**Last reviewed:** 2026-07-12

Two CI gates guard dependencies, and they gate **differently**:

- **`pip-audit`** (backend) has **no severity threshold** — it fails on *any* known
  advisory. The only suppression is `--ignore-vuln <ID>`. So the Python gate is
  **"zero un-waived advisories"**, and every ignored ID is a row below.
- **`pnpm audit --audit-level=high`** (frontend) filters by severity — the Node gate is
  **"zero un-waived HIGH+"**.

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

## Frontend — pnpm audit (`pnpm.auditConfig.ignoreGhsas` in `package.json`)

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
`@babel/plugin-transform-modules-systemjs`. All are transitive deps of `@angular/cli` /
`@angular-devkit/build-angular` / `karma` / `webpack-dev-server` — build- and test-time only.
The compiled bundle (`ng build`) contains none of them, so they are not a runtime attack
surface for end users. `pnpm overrides` were considered but rejected for a hardening PR
(forcing a dozen deep toolchain deps risks destabilising the build for zero shipped-code
benefit); the real fix is the deferred Angular 21 toolchain upgrade (Dependabot #9). Revisit
at that upgrade.

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
