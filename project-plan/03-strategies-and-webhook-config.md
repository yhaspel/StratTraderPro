# Milestone 03 — Strategies & Webhook Config

> **Week:** 3
> **Duration:** 5 working days
> **Depends on:** M02 (MFA & Profile)
> **Unlocks:** M04 (Webhook Ingest + IBKR Paper)

## 1. Purpose

Stand up the strategy domain: a catalogue of pre-seeded (system) strategies imported from the existing Trading Strategies project plus the ability for users to upload their own (pine + description + webhook JSON). Deliver the per-strategy Webhook Configuration UI with HMAC secret rotation and JSON-schema-validated payload templates. No alerts are processed yet; that lands in M04.

## 2. In Scope

- `strategies` Django app: models, views, serializers.
- Management command `load_strategies` that walks the Cowork Trading Strategies Project directory and seeds `is_system=true` rows.
- Upload endpoint accepting the three-file bundle (`<name>.pine`, `<name>_Description.txt`, `<name>_Webhook.json`) with validation.
- `WebhookConfig` with per-user, per-strategy HMAC secret, rotatable, with versioning.
- Public-format **webhook URL** generation (the endpoint itself is built in M04; here we generate and display the URL + secret only).
- Angular strategies feature area: list, detail, upload wizard, enable/disable, webhook configuration modal with Monaco editor + JSON schema validation + TradingView alert-template copy-button.
- Community-tested banner + accept-risk checkbox for uploaded strategies.

## 3. Out of Scope

- Processing actual inbound webhooks (M04).
- Backtesting strategies (M09).
- Strategy version history UI (stub migrations OK; UI later).
- Marketplace / sharing (post-MVP).

## 4. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-03-1 | `python manage.py load_strategies <path>` seeds all strategies found; rerun is idempotent. |
| AC-03-2 | Strategies list page shows system strategies with a "System" badge and any user-uploaded with a "Community-tested: No" warning banner. |
| AC-03-3 | A user can upload three files named `MyStrat.pine`, `MyStrat_Description.txt`, `MyStrat_Webhook.json`. On validation pass, strategy appears in their list. |
| AC-03-4 | Upload fails with a clear localized error if any filename stem mismatches, file exceeds size limits, webhook JSON doesn't parse, or required webhook keys are missing. |
| AC-03-5 | User must tick "I understand uploaded strategies are untested and I accept the risk" before upload submit is enabled. |
| AC-03-6 | "Configure webhook" modal displays the generated per-user-per-strategy URL and a one-time-reveal HMAC secret. |
| AC-03-7 | Rotating the secret invalidates the previous secret and produces a new URL+secret pair; version counter increments. |
| AC-03-8 | The webhook JSON schema editor accepts any valid JSON Schema draft 2020-12; invalid schema shows inline error; the user's payload-template is validated live against their schema. |
| AC-03-9 | A "Copy TradingView alert template" button produces a JSON block with `{{placeholders}}` and the current HMAC secret embedded in the `sig` field template — shown once per rotation. |
| AC-03-10 | System strategies cannot be deleted by users; they can only be toggled enabled/disabled per user. |
| AC-03-11 | A user can soft-delete their own uploaded strategy (sets `is_enabled=false`, excludes from list by default; admin-only hard delete). |
| AC-03-12 | All strategy and webhook endpoints require MFA per M02 enforcement. |

## 5. Definition of Done

Baseline DoD applies, plus:

- `load_strategies` command has an integration test using a fixture folder.
- Upload endpoint rejects path traversal in filenames (`../`, absolute paths, null bytes).
- Fernet-encrypted secrets verified not to appear in any log line.
- Monaco editor lazy-loaded (only on modal open) to keep bundle size in check.
- Help page "How to upload a strategy" written.

## 6. Implementation Tasks

### 6.1 Backend — models

```python
class Strategy(Model):
    id = UUIDField(...)
    owner = FK(User, null=True, related_name='strategies')   # NULL for system
    name = CharField(max_length=64)
    slug = SlugField(max_length=64)
    is_system = BooleanField(default=False)
    is_enabled = BooleanField(default=True)
    is_community_tested = BooleanField(default=False)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('owner', 'slug')

class StrategyFile(Model):
    id = UUIDField(...)
    strategy = FK(Strategy, related_name='files')
    kind = CharField(choices=[('PINE','PINE'),('DESC','DESC'),('WEBHOOK_TEMPLATE','WEBHOOK_TEMPLATE')])
    filename = CharField(max_length=128)
    sha256 = CharField(max_length=64)
    content = BinaryField(null=True)          # for small files
    object_url = CharField(max_length=512, null=True)  # for larger, S3-style
    size_bytes = IntegerField()
    uploaded_at = DateTimeField(auto_now_add=True)

class WebhookConfig(Model):
    id = UUIDField(...)
    user = FK(User)
    strategy = FK(Strategy)
    secret_encrypted = BinaryField()
    json_schema = JSONField()                 # draft 2020-12
    payload_template = JSONField()            # the default alert body we display in the Copy button
    version = PositiveIntegerField(default=1)
    rotated_at = DateTimeField(null=True)
    class Meta:
        unique_together = ('user', 'strategy')
```

### 6.2 Backend — upload validator

A DRF `ParserClass` accepts `multipart/form-data` with exactly three file parts. Validator:

- Derive stem from first file; assert the other two match `<stem>_Description.txt` and `<stem>_Webhook.json`.
- Regex stem: `^[A-Za-z0-9_\-]{3,64}$`.
- Size: pine ≤ 64 KB, desc ≤ 16 KB, webhook ≤ 16 KB.
- No null bytes, no path separators.
- `.pine` must start with `//@version=` within first 64 bytes (sanity check).
- `_Webhook.json` parses; contains required top-level keys (`strategy`, `action`, `symbol`, `qty`, `order_type`); unknown keys OK but logged.
- SHA-256 computed per file; duplicate-in-namespace rejected.
- Scan all three files for obvious XSS (`<script`, `javascript:`) before storing — defense in depth since the pine is displayed later.

### 6.3 Backend — views

```
GET    /api/v1/strategies/                 list (own + system)
POST   /api/v1/strategies/                 multipart upload
GET    /api/v1/strategies/{id}/
PATCH  /api/v1/strategies/{id}/            rename, toggle enabled
DELETE /api/v1/strategies/{id}/            soft delete
GET    /api/v1/strategies/{id}/files/{kind}/ download

GET    /api/v1/strategies/{id}/webhook-config/           get schema + url + reveal-once flag
PUT    /api/v1/strategies/{id}/webhook-config/           create/update schema + template
POST   /api/v1/strategies/{id}/webhook-config/rotate/    rotate secret; returns new secret once
GET    /api/v1/strategies/{id}/webhook-config/url/       returns URL + reveal-once secret (single use)
```

URL generation: `https://api.strattraderpro.com/hooks/v1/{user_uuid}/{strategy_uuid}/` (endpoint goes live in M04; here we just format and display).

### 6.4 Backend — `load_strategies` management command

```
python manage.py load_strategies /path/to/Trading_Strategies_Project/
```

Behavior:
- Walks the directory one level deep.
- For every stem with all three expected files, upsert a `Strategy(is_system=True)` and `StrategyFile` rows.
- Idempotent via SHA-256 check.
- `--dry-run` flag.
- Logs summary: `Seeded N strategies, updated M, skipped K.`

The path will be provided by Yuval when ready (§17 open question in master plan).

### 6.5 Frontend — strategies list

Route: `/strategies`. Layout:

- Table with columns: name, type (system / user), enabled, last run, backtested?, webhook status.
- Inline toggle for enabled.
- "Upload strategy" button → wizard.
- "Configure webhook" action per row → modal.

Data through `StrategiesFacade` + `StrategiesStore`. Fetch on entry; refresh on focus.

### 6.6 Frontend — upload wizard

3-step wizard using Angular CDK stepper:

1. **Select files** — 3 file inputs (or drag-and-drop) with filename validation shown live.
2. **Review** — preview the parsed description; show JSON schema hint from webhook JSON; show pine length.
3. **Acknowledge & submit** — mandatory checkbox: "I understand uploaded strategies are not tested by StratTraderPro. I accept the risk." + final upload.

Errors map to field-level messages. Size warnings show as yellow bars at 80% of limit.

### 6.7 Frontend — webhook modal

Modal components:

- **URL row** — read-only textbox + copy button.
- **Secret row** — masked with reveal button; reveal only works until the first "close modal" after rotation (store `_revealed_at` in store; invalidate after).
- **Rotate button** — confirm dialog: "This will break existing TradingView alerts. Proceed?"
- **JSON schema editor** — Monaco with JSON Schema intellisense (load the draft 2020-12 meta-schema).
- **Payload template editor** — Monaco; live-validates against the user's schema above.
- **Test button** — POSTs the template to a dry-run endpoint that returns "valid" or specific errors (does NOT call the webhook ingest).
- **Copy TradingView alert template button** — one-click copies a string like:
  ```
  {
    "strategy": "{{strategy}}",
    "action": "{{strategy.order.action}}",
    "symbol": "{{ticker}}",
    "qty": {{strategy.order.contracts}},
    "order_type": "MKT",
    "sig": "PASTE_YOUR_SECRET_HERE_<secret>",
    "idempotency_key": "{{strategy.order.id}}-{{time}}"
  }
  ```
  with `<secret>` filled in only at the moment the user just rotated (per §AC-03-9 reveal-once rule).

Accessibility: all buttons have `aria-label`; copy actions have screen-reader confirmations.

### 6.8 Frontend — route structure

```
/strategies
  list                    (default)
  :id/
    detail                (shows pine/desc previews, backtest link, webhook status)
    webhook-config        (modal or page)
  upload
```

Lazy-loaded `strategies.routes.ts`.

## 7. Tech Stack Notes

- Monaco lazy-loaded via dynamic import; bundle tracked on CI.
- `jsonschema` (Python) with `Draft202012Validator`.
- Secret rotation uses `secrets.token_urlsafe(48)` → encrypted before store.
- Signed URL display pattern: server returns `{ url, secret, expires_at }` only in the rotation endpoint; subsequent GETs return URL only.

## 8. Data Model Changes

Migrations:
- `strategies.0001_initial` — `Strategy`, `StrategyFile`, `WebhookConfig`.

## 9. API Contract Changes

Paths added per §6.3. Error codes: `STRATEGY_NOT_FOUND`, `STRATEGY_NAME_TAKEN`, `STRATEGY_FILE_MISMATCH`, `STRATEGY_FILE_TOO_LARGE`, `STRATEGY_WEBHOOK_INVALID`, `STRATEGY_SYSTEM_IMMUTABLE`, `WEBHOOK_SCHEMA_INVALID`.

## 10. Test Plan

### 10.1 Unit tests

- Upload validator: filename mismatch, oversize, bad JSON, missing required keys, path traversal.
- `load_strategies` idempotency with a fixture directory.
- `WebhookConfig.rotate()` increments version and invalidates old secret (old HMAC verification fails after).
- JSON Schema validator passes/fails predictably.

### 10.2 Integration

- End-to-end upload → GET list → enable → disable → delete (user strategy).
- System strategy cannot be deleted.
- Multi-user: user A cannot see or modify user B's strategies.

### 10.3 E2E (Playwright)

- `strategies.upload.spec.ts`: UI wizard happy path + each validation branch.
- `strategies.webhook.spec.ts`: open modal → rotate → verify URL/secret changes; copy TradingView template.
- Monaco lazy-load verified via network tab; chunk only loads on modal open.

### 10.4 Performance

- Strategies list renders ≤ 300ms with 50 strategies.
- Monaco lazy chunk ≤ 400 KB gzipped.

### 10.5 Security tests

- Path traversal in filename: `../etc/passwd.pine` rejected.
- XSS payloads in description file not rendered unsanitized.
- A malicious `_Webhook.json` with `__proto__` injection doesn't cause prototype pollution in frontend (JSON.parse is safe; reviewer verifies no `Object.assign` chains directly onto prototypes).
- Secret never appears in logs.

## 11. Security Considerations

- Uploaded pine is **never executed server-side**. It is stored as bytes and displayed as plain text (with pretty printing only; no highlighting that evaluates).
- When displayed, use `<pre><code>{{ text }}</code></pre>` with Angular's default escape.
- Webhook secrets Fernet-encrypted at rest.
- CSRF exempt unnecessary here — these are JWT-auth'd API routes.
- File inputs enforce MIME + magic-byte check server-side.
- Admin override: system strategies can only be edited by staff via Django admin.

## 12. Observability

- Prometheus: `strategy_uploads_total{result}`, `strategy_webhook_rotations_total`, `strategy_count_gauge`.
- Sentry captures validator errors as breadcrumbs, not exceptions.
- Log structured events: `strategy.upload.ok|rejected|error`, `strategy.webhook.rotate`.

## 13. Translation & Localization

- All UI copy keyed `strategies.*`, `webhook.*`.
- Validator error messages translated server-side via `gettext_lazy` so the UI can surface them directly.
- Schema/validator error messages from `jsonschema` library are English by default; wrap with our own translated prefix: `"{schema_error_prefix}: {library_message}"`.
- Monaco editor strings themselves not translated (library limitation; acceptable since editor is for developers).
- The "uploaded-strategies-untested" disclaimer has its own key and receives extra scrutiny in review.

## 14. Documentation Deliverables

- `/docs/adr/030-strategy-3-file-contract.md`
- `/docs/adr/031-webhook-hmac.md` — HMAC rotation + reveal-once reasoning.
- `/docs/runbooks/strategy-import-from-cowork.md`
- User help page: "Upload your first strategy" + "Configure your TradingView alert".

## 15. Rollback Plan

- Migration `strategies.0001` destructive on rollback (drops tables); user uploads would be lost. Before merging, document that this is greenfield: no prod data yet.
- Feature flag `STRATEGIES_V1_ENABLED` — if disabled, endpoints 503.
- Admin can disable a misbehaving user strategy via Django admin without a deploy.

## 16. Risks & Mitigations

| Risk | L | I | Mitigation |
|---|---|---|---|
| User treats "uploaded strategy" as tested by us | High | Med | Big red banner + mandatory checkbox + email confirmation on first enable. |
| Secret leaked via browser extension screenshot | Med | High | Reveal-once; auto-hide after 30s idle; no copy-to-clipboard without explicit user click; strongly worded UX. |
| Monaco editor bloats bundle | Med | Low | Lazy chunk; bundle-size CI gate. |
| `load_strategies` path mismatched → missing strategies | Med | Low | `--dry-run`, clear exit code, integration test with fixture. |

## 17. Exit Gate Checklist

- [ ] AC-03-1 … AC-03-12 pass.
- [ ] Upload validator covered by unit + integration tests.
- [ ] Seed command works on a sample fixture and, once Yuval provides the real path, on the actual Trading Strategies Project.
- [ ] Webhook rotation verified.
- [ ] A11y audit on strategies pages passes.
- [ ] Help pages published.
- [ ] Runbook committed.
- [ ] Tag `v0.3.0-strategies`.

Proceed to **M04 Webhook Ingest + IBKR Paper**.
