# ADR-030 — Strategy upload uses a strict 3-file contract

**Date:** 2026-05-03
**Status:** Accepted
**Milestone:** M03 — Strategies & Webhook Config

## Context

Users upload TradingView Pine strategies. We needed a single shape that:

1. Carries enough metadata to render a useful detail page (description).
2. Captures a structured payload schema so the M04 webhook ingest can
   validate inbound alerts before queueing them.
3. Is hard to abuse — pine bytes are user-controlled and end up in pages
   we render.

## Decision

User uploads MUST send three files in a single `multipart/form-data`
request, with the `<stem>` derived from the `.pine` filename:

- `<stem>.pine` — Pine script. ≤ 64 KB. Must declare `//@version=N`
  in the first 64 bytes.
- `<stem>_Description.txt` — TradingView-format description shown on the
  strategy detail page. ≤ 16 KB.
- `<stem>_Webhook.json` — payload template, also used as the editor's
  starting point. ≤ 16 KB. Required top-level keys: `strategy`, `action`,
  `symbol`, `qty`, `order_type`. Additional keys are permitted.

The stem itself is restricted to `[A-Za-z0-9_-]{3,64}`. Filenames are
validated for path traversal (`../`, `/`, `\`, null bytes) before the
stem is trusted.

A simple XSS scanner (substring check for `<script`, `javascript:`,
`onerror=`, `onload=`) runs over all three files. Defense-in-depth —
Angular's default text binding already escapes; this just rejects the
obvious cases at upload time.

## Consequences

**Positive:**
- One contract, one validator. The same `validate_uploaded_bundle()`
  function is reused for unit tests and the management command's
  integration tests.
- Naming convention is self-describing: a folder of three files with the
  same stem is unambiguously a strategy bundle.
- The webhook template comes for free with every strategy — no separate
  "configure your webhook payload first" step.

**Negative / trade-offs:**
- The real Trading Strategies project on disk does NOT follow this naming
  convention (it uses `<x>_strategy.pine` + `<x>-strategy-description.txt`
  with no webhook JSON). The `load_strategies` management command bridges
  this gap by:
  - Globbing for any `*.pine` and `*description*.txt` per folder.
  - Synthesizing a default `_Webhook.json` template when missing.
  This keeps the strict contract for uploads while letting us seed the
  existing catalogue without renaming files.
- `accept_untested_risk` is a separate, mandatory checkbox in the upload
  flow — not a setting on the strategy. Users must re-acknowledge per
  upload to dampen "I clicked through it once" muscle memory.

## Alternatives Considered

- **Single-file ZIP archive.** Easier in some ways, but harder to validate
  in pieces and surfaces a different attack surface (zip bombs, path
  traversal inside the archive). Rejected.
- **Two-file (pine + description) with the schema generated server-side.**
  Sounded simpler, but gives users no way to express their own payload
  shape — and they often need to add custom fields TradingView lets them
  template (e.g. their broker's `account_id`).

## See Also

- ADR-031 — Webhook HMAC rotation & reveal-once UX
- `apps/strategies/validators.py`
- `project-plan/03-strategies-and-webhook-config.md` §6.2
