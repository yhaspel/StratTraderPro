# OWASP ASVS Level 2 — Evidence Checklist

**Milestone:** M11 — Hardening, Security, Load Test & Docs
**Acceptance criterion:** AC-11-2 (§7.1)
**Standard:** OWASP ASVS 4.0.3, **Level 2 subset** (applicable chapters only — see scope note)
**Reviewed against:** `main` (post-M10; M11 hardening branch)
**Review date:** 2026-07-12
**Reviewer:** Solo-dev self-review + 24h cooldown re-check (DoD §11.2)
**Verdict legend:** ✅ **Pass** (evidence exists in-repo) · 📝 **Documented-Waiver** (deliberate, bounded gap with a rationale)

> **Scope note.** This is an ASVS **L2 subset** appropriate to a pre-beta, single-broker (Alpaca-live), no-live-trading (`ENABLE_LIVE_TRADING=false`) trading platform. Chapters are covered where the app has the corresponding surface. V6 (Stored Cryptography) is folded into V2/V8 (all at-rest crypto is a single Fernet primitive). Out-of-scope-by-decision items (JWT multi-`kid`, global DRF throttle, CSP-enforce) are recorded as **Documented-Waiver** with the governing plan reference, not silently omitted.
>
> Every evidence line is a real `path:line` or test method verified by reading the code, not a claim. Where a control's proof is a test, the **test asserts the failure mode**, per the M11 governing lesson (`bugs/README.md`): *a clean bill of health can be produced by the defect itself.*

---

## V1 — Architecture, Design & Threat Modeling

| Control | Verdict | Evidence |
|---|---|---|
| V1.1 Security decisions are documented as ADRs | ✅ Pass | `docs/adr/` holds numbered ADRs through **103**. Load-bearing security ADRs verified present: `042-webhook-secret-in-body.md` (static `sig` bearer model), `081-kill-switch-levels.md` (L0–L3), `100-audit-hash-chain.md` (append-only audit + scrub key set), `103-service-role-dispatch.md` (removes the silent-`web` default, BUG-011). |
| V1.4 Trust boundaries enforced server-side | ✅ Pass | Sizing inputs (regime, sentiment, equity, price) are gathered server-side and alerts cannot override them — `apps/risk/integration.py:1-7` (module docstring) + `_resolve_price` never fabricates a price (`integration.py:53-71`, FIX-H3). |
| V1.5 Auth & session components centralized | ✅ Pass | Project-wide auth class `ImpersonationAwareJWTAuthentication` set as the sole `DEFAULT_AUTHENTICATION_CLASSES` — `config/settings/base.py:223-225`; the impersonation write-block lives at the auth layer precisely because per-view `permission_classes` overrides would drop a global permission (`apps/users/authentication.py:1-13`). |

---

## V2 — Authentication

| Control | Verdict | Evidence |
|---|---|---|
| V2.1 Passwords stored with a modern memory-hard hash | ✅ Pass | **Argon2id** is the preferred hasher — `config/settings/base.py:208-214` (`Argon2PasswordHasher` first; legacy hashers retained only for transparent upgrade-on-login). |
| V2.1 Password strength enforced | ✅ Pass | `AUTH_PASSWORD_VALIDATORS` incl. a custom `LettersAndDigitsValidator` — `config/settings/base.py:201-204`. |
| V2.2 MFA available (TOTP) | ✅ Pass | RFC 6238 TOTP via **pyotp** — `apps/users/mfa.py:73-106` (`generate_totp_secret` 160-bit; `verify_totp` rejects non-6-digit, tolerates ±`MFA_TOTP_VALID_WINDOW`). Config: `MFA_TOTP_VALID_WINDOW=1` (±30s), `config/settings/base.py:294-296`. |
| V2.2 Single-use backup codes, hashed at rest | ✅ Pass | `generate_backup_codes` stores per-row salted SHA-256, returns plaintext once — `apps/users/mfa.py:125-147`; `consume_backup_code` atomic single-use mark — `mfa.py:150-163`. |
| V2.2 Step-up MFA is brute-force throttled | ✅ Pass | `verify_mfa_code` rejects **pre-verification** after `MFA_STEPUP_MAX_FAILURES` in `MFA_STEPUP_WINDOW_SECONDS`, emits `MFA_STEPUP_THROTTLED` audit (C3) — `apps/users/mfa.py:207-249`; config `base.py:275-279`. |
| V2.2 Account lockout on repeated failures | ✅ Pass | `FailedLoginAttempt` model + `is_locked` / `record_failed_login` / `clear_failed_logins` — `apps/users/services.py:219-234`; wired into `LoginView` at `apps/users/views.py:329,343,349,371`. Threshold 10 / 15-min window — `base.py:260-262`. Tests: `test_login_10th_failure_locks_account`, `test_login_after_lockout_expires_succeeds` (`apps/users/test_auth.py:186,199`). |
| V2.2 Anti-automation on auth endpoints | ✅ Pass | **django-ratelimit** per endpoint: login `5/m` per-email **+** `20/m` per-IP (`apps/users/views.py:396-397`); register `3/m` (`views.py:162`); password reset `3/m` (`views.py:513`); resend-verification `3/m` (`views.py:276`); MFA-verify throttled (`apps/users/views_m02.py:260`). |

---

## V3 — Session Management

| Control | Verdict | Evidence |
|---|---|---|
| V3.2 Stateless tokens signed, short access TTL | ✅ Pass | SimpleJWT **HS256**, access **15 min** / refresh **30 days** — `config/settings/base.py:242-255` (`ALGORITHM:"HS256"`, `ACCESS_TOKEN_LIFETIME` 15m @244, `REFRESH_TOKEN_LIFETIME` 30d @245). |
| V3.3 Refresh-token rotation with reuse detection | ✅ Pass | Custom `RefreshTokenFamily`: `rotate_refresh` revokes the whole family on a stale-`jti` replay — `apps/users/services.py:120-172` (`if jti != family.current_jti: family.revoke(reason="reuse_detected")` @155-157). Tests: `test_refresh_rotates_token`, `test_refresh_reuse_revokes_family` (`apps/users/test_auth.py:214,227`). |
| V3.3 Server-side revocation path exists | ✅ Pass | `rest_framework_simplejwt.token_blacklist` installed for belt-and-braces revocation of compromised tokens — `config/settings/base.py:67`; rationale `base.py:245-249`. |
| V3.3 Signing-key rotation | 📝 Documented-Waiver | JWT is **single-key HS256; no `kid`/multi-key** (frozen decision §4.4, out-of-scope §3). Rotation of `JWT_SIGNING_KEY` (`base.py:251`) invalidates in-flight access tokens (≤15 min) — handled as a **documented drain**, not multi-kid, in `docs/runbooks/secret-rotation.md` (§7.12 rehearsal). Building multi-kid is a feature and explicitly out of scope. |

---

## V4 — Access Control

| Control | Verdict | Evidence |
|---|---|---|
| V4.1 Default-deny; authenticated by default | ✅ Pass | `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]` — `config/settings/base.py:226-228`. |
| V4.1 MFA-gated sensitive endpoints | ✅ Pass | `IsAuthenticatedAndMFAEnforced` returns `MFA_REQUIRED` (403) when a view sets `mfa_required=True` and the user lacks MFA — `apps/users/permissions.py:22-39`. |
| V4.1 Admin surface requires staff + MFA, denies impersonation | ✅ Pass | `IsAdminAndMFAEnforced` requires authenticated + `is_staff` + `mfa_enabled` and **rejects impersonation tokens** — `apps/admin_portal/permissions.py:13-28`. |
| V4.2 BOLA/IDOR — cross-user object reads 404 (no oracle) | ✅ Pass | `apps/orders/test_pentest_authz.py`: `test_bob_cannot_read_alices_order_detail` (404, `:38`), `test_bobs_order_list_excludes_alices_orders` (`:46`), `test_bobs_positions_exclude_alices` (`:56`), `test_bob_cannot_read_alices_strategy` (404, `:61`). |
| V4.2 GDPR export/status owner-scoped | ✅ Pass | `apps/users/test_gdpr.py::test_export_status_is_owner_scoped` — Bob reading Alice's job → **404, not 403** (no existence oracle) — `test_gdpr.py:121-133`. |
| V4.3 Impersonation is read-only, enforced at the auth layer | ✅ Pass | `ImpersonationAwareJWTAuthentication` raises `PermissionDenied("Impersonation is read-only.")` for any non-SAFE_METHODS request and emits `admin.impersonated_read` — `apps/users/authentication.py:46-65`; realtime socket also refuses impersonation tokens — `apps/dashboard/consumers.py:33-35`. |

---

## V5 — Validation, Sanitization & Encoding

| Control | Verdict | Evidence |
|---|---|---|
| V5.1 Input validated server-side | ✅ Pass | DRF serializers on all `/api/v1/` surfaces (`REST_FRAMEWORK` default schema/serializer stack, `config/settings/base.py:219-237`). |
| V5.1 Webhook body validated against a JSON Schema | ✅ Pass | `jsonschema.validate(body_wo_sig, wc.json_schema)` → `WEBHOOK_SCHEMA_INVALID` 400 on failure — `apps/webhooks/views.py:162-176`. |
| V5.1 Webhook body size-capped before parse | ✅ Pass | 16 KB cap + content-type gate before JSON parse — `apps/webhooks/views.py:111-129`. |
| V5.3 Uploaded-file content validated (see also V12) | ✅ Pass | `validate_uploaded_bundle` — `apps/strategies/validators.py:113`. |

---

## V7 — Error Handling & Logging

| Control | Verdict | Evidence |
|---|---|---|
| V7.1 Secrets never written to logs — scrubber **wired**, not merely defined | ✅ Pass | **This was the M10 gap.** `SensitiveDataFilter` is a real `logging.Filter` (`config/log_scrub.py:17-24`) now **attached to the console handler**: `config/settings/base.py:734-736` declares the filter, `:751` lists `"scrub_sensitive"` in `handlers.console.filters`. Test `config/test_log_scrub.py::test_filter_is_wired_into_logging_config` asserts BOTH the declaration and the handler attachment (`:20-28`); `test_secret_in_extra_is_redacted` proves an `extra={"api_key":…,"password":…}` line is redacted (`:30-45`). Shared key set with the audit-row scrubber via `apps/audit/scrub.SENSITIVE_KEYS` (ADR-100). |
| V7.1 Uniform error envelope; no stack-trace leakage | ✅ Pass | `custom_exception_handler` — `config/settings/base.py:236`. Webhook generic-401 path (`WEBHOOK_SIG_BAD`) never distinguishes unknown-config from wrong-secret — `apps/webhooks/views.py:139-141,147-160`. |
| V7.3 No PII/secret frame-locals to error tracker | ✅ Pass | Sentry `include_local_variables=False` + `send_default_pii=False` — `config/settings/prod.py:142-159` (broker adapters build clients with plaintext keys as call args; frame locals off = no leak, AC-04-12). |

---

## V8 — Data Protection

| Control | Verdict | Evidence |
|---|---|---|
| V8.2 Secrets encrypted at rest (single Fernet KEK) | ✅ Pass | One `Fernet(settings.FERNET_KEK)` primitive wraps all secrets — `apps/users/mfa.py:42-67` (`_fernet`/`encrypt_secret`/`decrypt_secret`). Used by MFA TOTP secrets, webhook `sig`, and broker API keys. **No `MultiFernet` / DEK envelope in code** (frozen §0.6); rotation temporarily swaps `MultiFernet` per `docs/runbooks/mfa-kek-rotation.md` and reverts. |
| V8.2 Decrypt failure fails hard (no silent-accept) | ✅ Pass | `decrypt_secret` maps a KEK mismatch to `InvalidToken`, not a silent empty string — `apps/users/mfa.py:60-67`. |
| V8.3 Personal-data export **redacts** credentials | ✅ Pass | Defence-in-depth in `apps/users/gdpr.py`: an explicit export allowlist (`_export_sections`, `:73-124`) **plus** a field-name denylist that redacts any `secret/password/_enc/api_key/…` field (`SENSITIVE_FIELD_PARTS :27-38`, `serialize_instance :57-66`). AC-gating test `test_export_redacts_broker_and_mfa_secrets` asserts plaintext **and** ciphertext blobs are absent and `[REDACTED]` is present for broker/webhook secret fields — `apps/users/test_gdpr.py:81-109`. |
| V8.3 Right-to-erasure keeps audit integrity | ✅ Pass | `anonymize_user` scrubs PII **in place** (keeps the User PK so `AuditLog.user`/`actor` FKs resolve), drops credential rows, emits `account.anonymized` — `apps/users/gdpr.py:179-227`. Test `test_anonymize_expired_keeps_pk_and_scrubs_pii` — `apps/users/test_gdpr.py:232-260`. |

---

## V9 — Communications

| Control | Verdict | Evidence |
|---|---|---|
| V9.1 HSTS with preload + subdomains (prod) | ✅ Pass | `SECURE_HSTS_SECONDS=31_536_000`, `INCLUDE_SUBDOMAINS`, `PRELOAD` — `config/settings/prod.py:58-60`; secure cookies + proxy-SSL header `:55-57`. |
| V9.1 X-Content-Type-Options / Referrer-Policy | ✅ Pass | `SECURE_CONTENT_TYPE_NOSNIFF=True`, `SECURE_REFERRER_POLICY="strict-origin-when-cross-origin"` — `config/settings/base.py:802-803`. Test `config/test_security_headers.py::test_nosniff_and_referrer_policy` — `:20-23`. |
| V9.1 Permissions-Policy set | ✅ Pass | `SecurityHeadersMiddleware` emits `Permissions-Policy` (`config/security_headers.py:39-40`); default `geolocation=(),microphone=(),camera=(),payment=()` — `base.py:813-816`. Test `test_permissions_policy_present` — `config/test_security_headers.py:15-18`. |
| V9.1 Content-Security-Policy present | 📝 Documented-Waiver | **NEW in M11.** CSP ships **report-only** (frozen decision §4.6) — `SecurityHeadersMiddleware` emits `Content-Security-Policy-Report-Only` (`config/security_headers.py:31-38`) with `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` (`base.py:808-812`). The Django tier serves JSON + Swagger/browsable API, which a strict `enforce` would break; the flip is `CSP_REPORT_ONLY=false` once reports are clean (test `test_flip_to_enforcing` proves the flip emits the enforcing header — `config/test_security_headers.py:25-33`). Report-only vs. enforce is the bounded gap. |

---

## V10 — Malicious Code / Supply Chain

| Control | Verdict | Evidence |
|---|---|---|
| V10.3 Dependency vulnerabilities gate CI (Python) | ✅ Pass | **pip-audit** in `.github/workflows/ci.yml:97-101` — **no severity threshold**, fails on any advisory; suppression only via `--ignore-vuln <ID>`, each an entry in `docs/security/dependency-waivers.md`. |
| V10.3 Dependency vulnerabilities gate CI (Node) | ✅ Pass | **pnpm audit --audit-level=high** — `.github/workflows/ci.yml:150`; Node gate is zero un-waived HIGH+. |
| V10.3 Static analysis gate | ✅ Pass | `bandit -r apps/ config/ --severity-level medium` — `.github/workflows/ci.yml:70-71`. |
| V10.2 Legacy-credential leakage gate | ✅ Pass | `block-legacy-ibkr-creds` grep gate (TWS_* creds) — `.github/workflows/ci.yml:313`; runtime-config substitution gate `block-unsubstituted-runtime-config` `:345`. |

---

## V11 — Business Logic

| Control | Verdict | Evidence |
|---|---|---|
| V11.1 Kill-switch levels L0–L3 (not L1–L4) | ✅ Pass | `apps/risk/killswitch.py` (ADR-081): L0 per-strategy, L1 user-global, L2 daily-loss auto, L3 platform. Read path `is_blocked` orders platform→user→strategy (`:72-93`); write path `trigger_halt` with `SELECT FOR UPDATE` (`:99-138`); L3 blocks intake and does **not** flatten (`:136` `flatten and level != L3`). |
| V11.1 L2 daily-loss two-poll confirm + un-releasable same-day | ✅ Pass | `check_daily_loss(require_consecutive=2)` — two-poll SETNX confirmation avoids stale-mark false positives (`killswitch.py:241-290`); `release_halt` refuses same-trading-day L2 release (`:147`), auto-release only after NY-calendar rollover (`release_expired_l2_halts :293-303`). Fail-safe: a monitoring gap (`user_daily_pnl` → `None`) never auto-halts (`:202-238`). |
| V11.1 Deterministic sizing; alert cannot override params | ✅ Pass | `apply_sizing` — server-trusted inputs, fail-closed on broker-read failure (`apps/risk/integration.py:89-204`, `_persist_reject` on `SIZING_NO_EQUITY`/`SIZING_NO_PRICE`). |
| V11.1 RiskProfile limits **enforced** (not dead) | ✅ Pass | **M10.5 RISK-2** wired the previously-flagged fields: `permitted_asset_classes` → `SIZING_ASSET_CLASS_BLOCKED` before the broker read (`integration.py:123-128`); `max_concurrent` → `SIZING_MAX_CONCURRENT` on a new-symbol open at cap (`integration.py:132-142`); `leverage_cap` clamps gross notional to `equity × leverage_cap` (`apps/risk/sizing.py:100-105`), alongside the `max_position_pct` hard ceiling (`sizing.py:82,97`). |

---

## V12 — Files & Resources

| Control | Verdict | Evidence |
|---|---|---|
| V12.1 Upload size caps | ✅ Pass | `PINE_MAX_BYTES=64K`, `DESC_MAX_BYTES=16K`, `WEBHOOK_MAX_BYTES=16K` enforced per part — `apps/strategies/validators.py:27-29,168-179`. |
| V12.3 Path-traversal / null-byte rejection | ✅ Pass | `_reject_path_traversal` rejects empty, `\x00`, `/`, `\`, and `..` filenames — `apps/strategies/validators.py:80-96`; applied to every part (`:139`). Filename stem constrained to `^[A-Za-z0-9_\-]{3,64}$` (`STEM_REGEX :34,148`). |
| V12.5 Content-type sanity (Pine header check) | ✅ Pass | Pine file must declare `//@version=` within the first 64 bytes — `validators.py:184-189` (a polyglot PDF-as-Pine fails here). |
| V12.5 Stored-XSS scan of upload content | ✅ Pass | `_scan_for_xss` rejects `<script`, `javascript:`, `onerror=`, `onload=` in all three parts — `validators.py:43,99-108,190-192`. |

---

## V13 — API & Web Service

| Control | Verdict | Evidence |
|---|---|---|
| V13.1 Webhook auth = **static `sig` bearer secret**, constant-time compare (NOT HMAC-over-body) | ✅ Pass | `hmac.compare_digest(sig.encode(), expected.encode())` against the per-config Fernet-decrypted secret — `apps/webhooks/views.py:146-160` (ADR-042). Regression test `test_static_bearer_model_authenticates_sender_not_body` pins the bearer model: a valid secret with an **altered body field still passes** the sig gate, so nobody can "harden" it into a body-integrity HMAC by accident — `apps/webhooks/test_pentest.py:66-76`. |
| V13.1 No cross-user / path-swap secret reuse | ✅ Pass | `test_cross_user_secret_cannot_drive_another_users_endpoint` (401, `apps/webhooks/test_pentest.py:41-45`); `test_swapped_strategy_uuid_in_path_rejected` (`:47-50`). |
| V13.1 No existence oracle | ✅ Pass | Unknown user/strategy and wrong-secret both return identical `WEBHOOK_SIG_BAD` 401 — `views.py:139-141`; test `test_no_existence_oracle_for_unknown_vs_wrong_secret` (`test_pentest.py:78-86`). |
| V13.4 Replay protection (idempotency) | ✅ Pass | `cache.add` SETNX on `idem:{user}:{sha256(key)}`, 24h TTL → duplicate returns 200 `{duplicate:true}`, no double-order — `views.py:178-187`; test `test_idempotency_replay_is_deduped_not_double_ordered` (`test_pentest.py:52-64`). |
| V13.4 Per-endpoint rate limiting | ✅ Pass | Webhook fixed-window per-user counter `_rate_limited` (`views.py:75-88,101-103`); auth endpoints via django-ratelimit (see V2). |
| V13.4 **Global** DRF throttle | 📝 Documented-Waiver | There is **no** `DEFAULT_THROTTLE_*` in `REST_FRAMEWORK` (`config/settings/base.py:219-237`). By decision (§7.1 V13) the control is **per-endpoint** `django-ratelimit` + the webhook fixed-window counter, not a global throttle. The bounded gap: `/api/v1/` read endpoints behind JWT are not globally rate-limited; documented here as the accepted design, revisit if abuse is observed. |
| V13.1 CORS is an allowlist (prod) | ✅ Pass | `CORS_ALLOWED_ORIGINS` env-driven, empty default (`config/settings/prod.py:69`); `corsheaders` middleware installed (`base.py:65,113`). |

---

## V14 — Configuration

| Control | Verdict | Evidence |
|---|---|---|
| V14.1 `DEBUG=False` in production | ✅ Pass | `config/settings/prod.py:12`. |
| V14.2 Secrets from env only; no committed secrets | ✅ Pass | `SECRET_KEY`, `FERNET_KEK`, `JWT_SIGNING_KEY` all `env(...)` — `base.py:251,290`; dev defaults derive from `SECRET_KEY` only for unprovisioned test/runserver. Bandit + the legacy-cred grep gate (V10) backstop against committed secrets. |
| V14.2 Prod **fails closed** on insecure/missing keys (C2) | ✅ Pass | `prod.py:28-50` re-reads `SECRET_KEY`/`FERNET_KEK` with **no default** (django-environ raises if unset) and raises `ImproperlyConfigured` on the known insecure dev values; JWT signing key checked too (`:47-50`). |
| V14.4 Metrics endpoint fails closed in prod | ✅ Pass | `METRICS_REQUIRE_AUTH=True`; `/metrics` returns 401 if `METRICS_BASIC_AUTH_*` unset (M10) — `prod.py:92-97`; creds `base.py:791-792`; auth check `config/metrics_endpoint.py:45-46`. |
| V14.4 Security headers active in the middleware chain | ✅ Pass | `SecurityMiddleware` (`base.py:110`) + `config.security_headers.SecurityHeadersMiddleware` (`base.py:112`) both in `MIDDLEWARE`. |

---

## Summary

| Chapter | Pass | Documented-Waiver |
|---|---|---|
| V1 Architecture | 3 | 0 |
| V2 Authentication | 7 | 0 |
| V3 Session | 3 | 1 |
| V4 Access Control | 6 | 0 |
| V5 Validation | 4 | 0 |
| V7 Error/Logging | 3 | 0 |
| V8 Data Protection | 4 | 0 |
| V9 Communications | 3 | 1 |
| V10 Supply Chain | 4 | 0 |
| V11 Business Logic | 4 | 0 |
| V12 Files | 4 | 0 |
| V13 API | 6 | 1 |
| V14 Configuration | 5 | 0 |
| **Total** | **56** | **3** |

**59 applicable L2 controls: 56 Pass, 3 Documented-Waiver, 0 unresolved failures.**

The three waivers are deliberate, bounded, and each carries a plan reference and a flip/revisit path:

1. **V3.3 JWT signing-key rotation** — single-key HS256 drain (frozen §4.4); multi-`kid` is out of scope (§3). Runbook: `docs/runbooks/secret-rotation.md`.
2. **V9.1 CSP enforce** — ships report-only (frozen §4.6); flip via `CSP_REPORT_ONLY=false` once violation reports are clean (`test_flip_to_enforcing` proves the flip works).
3. **V13.4 global DRF throttle** — per-endpoint `django-ratelimit` + webhook fixed-window is the chosen control (§7.1 V13); no `DEFAULT_THROTTLE_*`. Revisit if abuse is observed.
