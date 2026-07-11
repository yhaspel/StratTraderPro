# BUG-001 — OTel never traced the web tier (entrypoint ordering)

| | |
|---|---|
| **Severity** | S2 — a shipped feature was silently non-functional in production |
| **Status** | FIXED (commit `dac9643`, 2026-07-11) |
| **Area** | Observability / OpenTelemetry |
| **Affected** | M10 (`v0.10.0-admin`) through `2c1207b` — i.e. tracing never worked, from the day it shipped |
| **Found** | 2026-07-11, during M10 Section-B operator setup (B5), while verifying traces landed in Tempo |

## Symptom

With `OTEL_EXPORTER_OTLP_ENDPOINT` + `OTEL_EXPORTER_OTLP_HEADERS` correctly set on
the Railway backend service:

- `config.otel` logged `otel.initialized … otlp: true` on every gunicorn worker
- **no** OTel errors in the deploy logs
- **no** export failures in the deploy logs
- Grafana Tempo: zero traces, and the Service Name picker was empty

Every signal said "healthy". Nothing was being traced.

## Root cause

`config/wsgi.py` (and `config/asgi.py`) initialised OTel **after** constructing the
Django application:

```python
_django_app = get_wsgi_application()   # 1. builds WSGIHandler -> load_middleware()
...
init_otel()                            # 2. DjangoInstrumentor().instrument()
```

`DjangoInstrumentor` activates by **inserting its middleware into
`settings.MIDDLEWARE`** (see
`opentelemetry/instrumentation/django/__init__.py::DjangoInstrumentor._instrument`,
which does `getattr(settings, "MIDDLEWARE")` → `insert(...)` → `setattr(...)`).

But Django freezes the middleware chain when the handler is constructed —
`WSGIHandler.__init__` calls `self.load_middleware()`, which reads
`settings.MIDDLEWARE` *at that moment*. Initialising OTel afterwards mutates a
list that nothing reads again, so the OTel middleware is never in the request
path and **zero request spans are created**.

The exporter itself was fine — it just never had any spans to export, which is
exactly why there were no errors anywhere.

## Why CI never caught it

The M10 test suite asserted that spans carry the right attributes using an
**in-memory span exporter**, creating spans directly. Nothing asserted that the
*real WSGI entrypoint* actually produces a span for a real request. The
instrumentation was tested; the wiring was not.

## Fix

`init_otel()` now runs **before** `get_wsgi_application()` / `get_asgi_application()`:

```python
from config.otel import init_otel
init_otel()

_django_app = get_wsgi_application()
```

Both entrypoints carry an `ORDER IS LOAD-BEARING` comment explaining why, so it
isn't "tidied" back.

## Verification

- Local repro (real Django + OTel + `InMemorySpanExporter`, driving a real WSGI
  request): buggy order → **0 spans**; fixed order → **1 span** (`GET healthz`).
- Production, after deploy: Tempo shows service `strattraderpro-backend` with
  spans `GET api/v1/strategies/` (4 ms) and `GET` (9 ms).

## Regression test

`backend/config/test_otel_export.py::EntrypointOrderTests` asserts
`init_otel()` precedes `get_*_application()` in both entrypoints.

It parses the module with **`ast`**, not string search — the first draft of this
test passed against the buggy code because the word `get_wsgi_application()`
appeared in the explanatory *comment* above the call. Comments must not be able
to satisfy the guard.

## Follow-up

- [ ] Consider an end-to-end smoke assertion (a real request through
      `config.wsgi:application` produces ≥1 span) so the whole chain — not just
      the ordering — is covered.
- [ ] See BUG-006: the `otel.initialized` log line is now swallowed, because init
      runs before Django configures logging. Tracing works, but boot-time
      confirmation of it is gone.
