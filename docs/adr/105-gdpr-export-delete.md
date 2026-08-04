# ADR-105 — GDPR personal-data export + anonymize-in-place soft delete

**Date:** 2026-07-12
**Status:** Accepted
**Milestone:** M11 — Hardening, Security, Load Test & Docs
**Reference:** `project-plan/11-hardening-and-load-test.md` §7.7 (frozen decisions §4.2, §4.3); AC-11-8 [CI], AC-11-9 [CI]; R2 bucket is [LIVE] (AC-11-10);
`backend/apps/users/gdpr.py`, `backend/apps/users/views_gdpr.py`, `backend/apps/users/tasks.py`,
`backend/apps/users/models.py` (`DataExportJob`), `backend/apps/users/migrations/0005_delete_flow_and_terms.py`,
`backend/apps/users/metrics_gdpr.py`, `backend/apps/users/test_gdpr.py`,
`backend/config/settings/base.py` (`STORAGES['exports']`), `backend/config/settings/prod.py`,
`backend/apps/audit/models.py` (FK `on_delete`), `backend/apps/audit/migrations/0002_chain_triggers.py` (append-only trigger)

## Context

Beta onboards external users, which brings GDPR/CCPA obligations: a data-subject
**access** right (export everything we hold on you) and an **erasure** right (delete my
account). Two constraints make the naïve implementations wrong:

1. **We hold secrets at rest.** MFA TOTP secrets, the webhook `sig`, and broker API
   keys are all encrypted with a single `Fernet(settings.FERNET_KEK)` (`apps/users/mfa.py`).
   A personal-data export that dumped model rows verbatim would leak those secrets (as
   ciphertext, but still material we must never egress). Redaction cannot be an
   afterthought — it is an AC-gating test (AC-11-8).

2. **The audit log is append-only and hash-chained (ADR-100).** `AuditLog` rows carry a
   Postgres trigger, `audit_log_block_mutation`, that `RAISE`s on **any** `UPDATE` or
   `DELETE` for every DB role (`apps/audit/migrations/0002_chain_triggers.py:8,19-23`).
   `AuditLog.user`/`AuditLog.actor` are `on_delete=SET_NULL` (`apps/audit/models.py:24-33`),
   but that only fires if the `User` is actually deleted. A hard `DELETE` of a `User` would
   either null its audit FKs (losing the actor identity on historical events) or, under a
   `CASCADE`, attempt to delete the chained rows the trigger forbids — the transaction would
   abort. Erasure therefore cannot be "delete the row."

There was no object storage in the codebase before M11 (§0.9), so the export also needs a
storage backend that is testable locally but S3-compatible in production.

## Decision

### Export — async job → ZIP → `STORAGES['exports']` → 24h signed URL

`GET /api/v1/users/me/export/` (`DataExportRequestView`, `views_gdpr.py:46`) creates a
`DataExportJob` (status `PENDING`), emits `account.export_requested`, and enqueues
`run_data_export.delay(job_id)` on the default `celery` queue — the queue §7.0/ADR-103 fixed
so it actually has a consumer. An in-flight `PENDING`/`RUNNING` job is **reused** rather than
stacked (`views_gdpr.py:56-64`; `test_export_reuses_active_job`).

`run_data_export` (`tasks.py:34`) calls `build_export_zip(user)` (`gdpr.py:157`), which streams
one JSON document per data category into an in-memory `zipfile.ZipFile`/`io.BytesIO`
(`gdpr.py:165-173`) — small per-user payloads stay well within memory — then saves the bytes to
the storage abstraction:

- Access is always via `django.core.files.storage.storages["exports"]` (`tasks.py:23-25`), never
  a hard-coded backend.
- **Dev/test:** `FileSystemStorage` (`config/settings/base.py:703-713`).
- **Prod:** `storages.backends.s3.S3Storage` pointed at Cloudflare R2, wired **only when
  `EXPORTS_BUCKET` is set** (`config/settings/prod.py:105-122`).
- **Tests:** `moto` `mock_aws` proves the S3 path end-to-end
  (`GDPRExportS3Tests.test_export_to_s3_produces_24h_presigned_url`, `test_gdpr.py:151-201`).

The download link is time-limited: `signed_export_url` returns `storage.url(file_key)`
(`tasks.py:28-31`); R2's backend signs a presigned URL with
`querystring_expire = EXPORT_SIGNED_URL_TTL_SECONDS` (default `86_400` = 24h,
`base.py:716`, `prod.py:118`). `GET /api/v1/users/me/export/{job_id}/`
(`DataExportStatusView`, `views_gdpr.py:76`) returns the URL only when the job is `READY` and
not expired, and is **owner-scoped** — a non-owner (or bad id) always gets a generic 404 with no
existence oracle (`views_gdpr.py:82-85`; `test_export_status_is_owner_scoped`).

### Defence-in-depth redaction (allowlist + field-name denylist)

Redaction does not rely on a single mechanism:

- **Explicit allowlist** — `_export_sections` (`gdpr.py:73-124`) is the *source of truth for
  WHAT* is exported: `account`, `profile`, `terms_acceptances`, `strategies`,
  `webhook_configs`, `broker_accounts`, `orders`, `fills`, `positions`, `recon_events`,
  `alerts`, `sizing_decisions`, `risk_events`, `backtests`, and the user's own `audit_log`
  rows (`_audit_rows`, `gdpr.py:127-131`; `test_export_includes_user_own_audit_rows`).
- **Field-name denylist** — the *backstop for HOW* each row is serialized. `serialize_instance`
  (`gdpr.py:57-66`) replaces any field whose name matches `SENSITIVE_FIELD_PARTS`
  (`secret`, `password`, `_enc`, `encrypted`, `token_hash`, `api_key`, `api_secret`, …,
  `gdpr.py:27-38`) with `[REDACTED]`, so a future field added to an exported model cannot
  silently leak — even the Fernet ciphertext blobs are excluded, not merely re-encoded.
  `test_export_redacts_broker_and_mfa_secrets` (`test_gdpr.py:81`) asserts the denylist bites.

### Erasure — 30-day **soft** delete = anonymize-in-place, never hard-delete

`POST /api/v1/users/me/delete/` (`AccountDeleteView`, `views_gdpr.py:105`) sets
`pending_delete_at = now + 30d` (`DELETE_WINDOW`, `views_gdpr.py:33,116`), emits
`account.delete_requested`, and sends a confirmation email. The window is reversible:
`POST /api/v1/users/me/delete/cancel/` (`AccountDeleteCancelView`, `views_gdpr.py:139`) clears
`pending_delete_at` (`test_delete_cancel_clears_pending`).

The nightly beat task `anonymize_expired_accounts` (`tasks.py:110`) processes every account
whose window has expired and calls `anonymize_user` (`gdpr.py:179-227`), which:

- **Keeps the `User` row under its PK** and scrubs PII *in place*: `email` →
  `deleted-<uuid>@anonymized.invalid`, `display_name` → `"deleted user"`, `is_active=False`,
  `set_unusable_password()`, `pending_delete_at=None`.
- **Deletes only credential/secret rows** that are useless once the account is dead —
  `MFADevice`, `BackupCode`, `BrokerAccount` (so no dead ciphertext lingers).
- Emits an `account.anonymized` audit event recording the erasure.

The `User` PK is deliberately preserved so `AuditLog.user`/`actor` FKs keep **resolving to a
scrubbed row** instead of dangling or nulling. `test_anonymize_expired_keeps_pk_and_scrubs_pii`
(`test_gdpr.py:232`) proves the PK survives, PII is gone, the audit FK still resolves, and an
`account.anonymized` row exists; `test_anonymize_skips_non_expired` (`test_gdpr.py:262`) proves
the window is honoured.

### Data model — `users.0005_delete_flow_and_terms`

Additive and reversible (§16 rollback): `User.pending_delete_at` (nullable, indexed);
`DataExportJob` (`status` ∈ `PENDING/RUNNING/READY/FAILED/EXPIRED`, `file_key`, `size_bytes`,
`expires_at`, `is_expired` property, `models.py:449-483`); `TermsDocument`; `TermsAcceptance`.
New metrics live in a module-level `metrics_gdpr.py` (multiproc-safe): `EXPORT_REQUESTS_TOTAL`,
`EXPORT_JOBS_TOTAL`, `EXPORT_DURATION_SECONDS`, `DELETE_REQUESTS_TOTAL`,
`TERMS_ACCEPTANCES_TOTAL`.

## Why hard-delete + cascade was rejected

Deleting the `User` row on erasure is the obvious implementation and it breaks the audit
chain's integrity guarantee. A `CASCADE` from `User` to `AuditLog` would attempt to delete
chained rows, which `audit_log_block_mutation` `RAISE`s on — the anonymization transaction
would abort and no account would ever be erased. `SET_NULL` avoids the abort but discards the
actor identity on every historical event that user touched, defeating the point of a
tamper-evident, attributable log (ADR-100). Anonymize-in-place is the only option that
satisfies erasure (no PII survives) **and** integrity (the chain and its FKs stay intact): we
keep an inert, scrubbed PK row forever, which is an acceptable cost.

## Consequences

- **Positive.** GDPR access + erasure are self-serve and audited end-to-end
  (`export_requested`/`export_ready`/`export_failed`/`delete_requested`/`delete_cancelled`/
  `anonymized` events). Redaction is defence-in-depth, so adding a field to an exported model
  cannot regress into a secret leak. The audit hash chain and its actor FKs remain valid across
  erasure. Storage is one swappable alias (`FileSystemStorage` dev / R2 prod / `moto` test), so
  the tested path and the shipped path share the same code.
- **R2 is a [LIVE] operator step, with graceful degradation.** Prod switches
  `STORAGES['exports']` to `S3Storage` **only if `EXPORTS_BUCKET` is set**; otherwise
  `EXPORTS_STORAGE_READY=False` (`prod.py:124-125`, `base.py:717-720`) and `run_data_export`
  leaves the job **`PENDING`** with an operator note rather than crashing on an unconfigured
  backend (`tasks.py:53-61`; risk §17). To use object storage the operator provisions an
  S3-compatible bucket plus `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_S3_ENDPOINT_URL`;
  otherwise prod falls back to the filesystem `exports` backend and requests complete locally.
- **Reversibility costs 30 days of retained PII.** Soft delete deliberately keeps the account's
  PII for up to 30 days so a mistaken request can be cancelled — a conscious tradeoff over
  immediate erasure. After expiry, the scrubbed PK row persists indefinitely (it is inert and
  carries no PII).
- **Endpoints are `IsAuthenticated`, not MFA-gated** (`views_gdpr.py` module docstring): GDPR
  rights must be exercisable by any account, and delete is reversible + email-confirmed.
  Impersonation tokens are write-blocked at the auth layer, so an admin impersonating a user
  cannot POST a delete/accept on their behalf.
