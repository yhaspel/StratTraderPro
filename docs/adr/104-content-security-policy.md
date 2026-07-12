# ADR-104 — Content-Security-Policy via a report-only SecurityHeadersMiddleware

**Date:** 2026-07-12
**Status:** Accepted
**Milestone:** M11 — Hardening, Security, Load Test & Docs
**Reference:** `project-plan/11-hardening-and-load-test.md` §4.6 (frozen decision), §7.1 V9,
AC-11-2 [CI]; `backend/config/security_headers.py`,
`backend/config/test_security_headers.py`,
`backend/config/settings/base.py` (`MIDDLEWARE` @ 106–122, `CSP_*` @ 798–816),
`backend/config/settings/prod.py` (`SECURE_HSTS_*` @ 58–60), `docker/nginx.conf.template`

## Context

The M11 hardening pass (ASVS L2 subset, §7.1 **V9 Communications**) requires a
Content-Security-Policy on top of the header set Django already emits. Before M11
the backend set HSTS / Referrer-Policy / X-Content-Type-Options via Django's own
`SecurityMiddleware` (`SECURE_HSTS_SECONDS` etc. in `prod.py:58`,
`SECURE_CONTENT_TYPE_NOSNIFF` / `SECURE_REFERRER_POLICY` in `base.py:802-803`), but
carried **no CSP and no Permissions-Policy** — Django has no native setting for
either.

The awkward part is *what* the Django tier serves. It is an API tier: JSON responses
(for which CSP is inert — there is no script/style/`<img>` context for the browser to
constrain) plus two HTML surfaces that are decidedly *not* inert — the
drf-spectacular **Swagger UI** and the **DRF browsable API**, both of which load
scripts and inline styles that a strict `default-src 'none'` would block outright
under an *enforcing* policy. Turning on a real CSP in enforce mode on day one would
therefore break exactly the developer-facing UIs the header does the least for, while
buying nothing on the JSON paths that are the actual product surface. The SPA that
users see is served by a **separate** frontend container (`docker/nginx.conf.template`),
not by Django — its CSP is a different response, from a different origin, and belongs
there.

Frozen decision §4.6 settles the sequencing: **CSP ships report-only first, then
enforce.** This ADR records how that is implemented and why a middleware — not a
dependency — carries it.

## Decision

**Add a custom `SecurityHeadersMiddleware` (`backend/config/security_headers.py`) that
emits the CSP and Permissions-Policy, and ship the CSP REPORT-ONLY by default**, flipped
to enforcing by a single env var.

- The middleware is wired into `MIDDLEWARE` immediately after Django's
  `SecurityMiddleware` (`base.py:112`), so it decorates every Django response while
  leaving the natively-handled headers (HSTS / nosniff / Referrer-Policy) to
  `SecurityMiddleware`. It fills only the two gaps Django has no setting for: CSP and
  Permissions-Policy.
- **Report-only is the default.** The middleware chooses the header name from
  `settings.CSP_REPORT_ONLY` (`security_headers.py:31-35`): `True` →
  `Content-Security-Policy-Report-Only`, `False` → `Content-Security-Policy`.
  `CSP_REPORT_ONLY = env.bool("CSP_REPORT_ONLY", default=True)` (`base.py:808`), so the
  policy is observed-but-not-enforced until an operator sets `CSP_REPORT_ONLY=false`.
- **The policy is strict by default:**
  `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`
  (`CSP_POLICY`, `base.py:809-812`). Strict is safe here precisely because it is inert
  on JSON and only *reported* — never enforced — on the Swagger / browsable-API UIs
  until the flip. Permissions-Policy defaults to
  `geolocation=(), microphone=(), camera=(), payment=()` (`base.py:813-816`).
- **Both headers use `setdefault` semantics** (`security_headers.py:37-40`): the
  middleware never clobbers a header a view already set. Settings are read
  **per-request** rather than cached in `__init__`, so a config change or a test
  `override_settings` takes effect without rebuilding the middleware.
- **The flip is a one-line, tested operation, not a code change.** `test_flip_to_enforcing`
  (`test_security_headers.py:25-33`) sets `CSP_REPORT_ONLY=False` and asserts the
  enforcing `Content-Security-Policy` header appears; `test_csp_report_only_present`
  (`test_security_headers.py:8-13`) asserts the default response carries
  `Content-Security-Policy-Report-Only` with `default-src 'none'` and that the enforcing
  header is *absent*.

## Why `django-csp` was rejected

`django-csp` is the obvious library choice, and it was rejected on cost-vs-benefit.
The behaviour we need is genuinely small: pick one of two header names from a boolean,
emit a static policy string, and don't clobber a view that set its own — roughly
twenty lines, fully expressed in `security_headers.py`. `django-csp` would add a new
runtime dependency (and a new middleware) to earn per-directive settings and nonce
plumbing that a JSON API tier with a `default-src 'none'` policy does not use. It also
adds another entry to the **`pip-audit` surface** M11 is simultaneously tightening
(AC-11-1) and another package to keep patched — real, recurring cost for no functional
gain here. A twenty-line middleware we own is easier to reason about, has zero advisory
surface, and reads its config live for testability. If the policy ever grows nonces or
per-route directives, revisiting `django-csp` is cheap; committing to it now is not.

## Consequences

- **Positive:** the backend ships a real, strict CSP and a Permissions-Policy on every
  response with no new dependency; the header is *reported*, not enforced, so it cannot
  break Swagger / the browsable API before violations are reviewed; the report-only →
  enforce flip is env-only and covered by a test that proves both states; the
  natively-handled headers stay with `SecurityMiddleware`, so there is one owner per
  header.
- **Scope boundary:** this covers the **Django tier only**. The user-facing SPA's CSP is
  a separate response from the frontend nginx (`docker/nginx.conf.template`) and is
  explicitly out of scope for this ADR — a JSON-tier CSP does nothing for the HTML the
  browser actually renders for the app.
- **Follow-up — the flip to enforce.** M11 lands report-only. Flipping to enforce
  (`CSP_REPORT_ONLY=false`) is deferred until a report window shows the app pages are
  clean, per §4.6. Because Swagger / the browsable API would be the ones to break, the
  flip should either be scoped away from those routes or accept a laxer policy for them;
  that is a tracked follow-up, not a merge blocker. Nothing in the code path changes at
  flip time — only the env var — so the follow-up is an operator action plus a report
  review, not a new PR.
