# BUG-006 — `otel.initialized` log line is swallowed

| | |
|---|---|
| **Severity** | S4 — papercut, but it removes the only boot-time confirmation that tracing is on |
| **Status** | OPEN |
| **Area** | Observability / logging |
| **Introduced by** | the BUG-001 fix (`dac9643`) — a deliberate, accepted trade-off |

## Symptom

Before the BUG-001 fix, each gunicorn worker logged on boot:

```
otel.initialized  name: config.otel  levelname: INFO  otlp: true
```

After the fix, this line is **gone** from the deploy logs — even though tracing
now genuinely works (spans are reaching Tempo).

## Root cause

The BUG-001 fix moved `init_otel()` **before** `get_wsgi_application()`. But
Django configures logging inside `django.setup()`, which `get_wsgi_application()`
triggers. So at the moment `init_otel()` runs, `settings.LOGGING` has not been
applied yet: the root logger has no handlers, and an `INFO` record is dropped
(Python's `logging.lastResort` only emits `WARNING`+).

So the message isn't lost to a bug in OTel — it's emitted into a logging system
that isn't configured yet.

Note this cuts both ways, and the *useful* half still works: a failure inside
`init_otel()` is logged via `logger.exception(...)` at `ERROR`, which **does**
reach stderr through `lastResort`. So a broken init would still be visible; only
the success confirmation is missing.

## Impact

Minor, but real: "is tracing actually enabled on this deploy?" is no longer
answerable from the logs. During the BUG-001 investigation this ambiguity was
itself a source of confusion — the absence of `otel.initialized` briefly looked
like a *regression* rather than a logging artefact.

## Options

1. **Emit at `WARNING`** — crude; pollutes logs with a non-warning.
2. **Defer the log line**: have `init_otel()` stash its result and log it lazily
   on first use (or from a Django `AppConfig.ready()`, which runs after logging is
   configured). Keeps init early, restores the confirmation.
3. **Configure logging explicitly before `init_otel()`** via
   `logging.config.dictConfig(settings.LOGGING)`. Most direct, but duplicates
   what `django.setup()` will do moments later.
4. **Accept it** and rely on the end-to-end check (a span in Tempo) instead of a
   boot log.

Recommendation: option 2 — the confirmation is worth keeping, and it is exactly
the signal you want during an incident.

## Follow-up

- [ ] Pick an option and restore a boot-time (or first-request) confirmation that
      OTLP export is enabled.
