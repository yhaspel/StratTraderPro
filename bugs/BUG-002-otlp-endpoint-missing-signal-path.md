# BUG-002 — OTLP exporter given base URL; `/v1/traces` never appended

| | |
|---|---|
| **Severity** | S2 — would have silently dropped 100% of spans |
| **Status** | FIXED (commit `dac9643`, 2026-07-11) |
| **Area** | Observability / OpenTelemetry |
| **Affected** | M10 (`v0.10.0-admin`) through `2c1207b` |
| **Found** | 2026-07-11, while diagnosing BUG-001 |

## Symptom

Latent — masked by BUG-001. Because no spans were ever *created*, none were ever
*exported*, so this second defect could not manifest. It would have bitten
immediately after BUG-001 was fixed.

## Root cause

`config/otel.py` passed the OTLP **base** URL straight to the HTTP span exporter:

```python
endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT   # ".../otlp"
OTLPSpanExporter(endpoint=endpoint)
```

The OTLP/HTTP exporter only appends the `/v1/traces` signal path when it resolves
the endpoint **from the environment itself**. From
`opentelemetry/exporter/otlp/proto/http/trace_exporter/__init__.py`:

```python
self._endpoint = endpoint or environ.get(
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    _append_trace_path(environ.get(OTEL_EXPORTER_OTLP_ENDPOINT, DEFAULT_ENDPOINT)),
)
```

An endpoint passed **explicitly** short-circuits the `or` and is used verbatim.
So spans would have been POSTed to `https://otlp-gateway-…/otlp` instead of
`https://otlp-gateway-…/otlp/v1/traces` → 404 → dropped.

`BatchSpanProcessor` swallows export failures by design, and `init_otel()` wraps
everything in a broad `except` ("tracing must never break boot"), so this would
have failed **silently**, exactly like BUG-001.

## Note on the auth header (not a bug)

Grafana Cloud's generated config uses a URL-encoded space:

```
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20<base64>"
```

This is correct and works: the SDK's `parse_env_headers()` calls `unquote(value)`,
so the header is sent as `Authorization: Basic <base64>`. Investigated and ruled
out — recorded here so nobody re-chases it.

## Fix

Normalize the endpoint to the traces signal URL, idempotently, so the env var may
hold either the OTLP base URL or the full signal URL:

```python
def _traces_endpoint(endpoint: str) -> str:
    url = endpoint.rstrip("/")
    return url if url.endswith("/v1/traces") else f"{url}/v1/traces"

OTLPSpanExporter(endpoint=_traces_endpoint(endpoint))
```

## Operational note

While diagnosing, the Railway shared variable `OTEL_EXPORTER_OTLP_ENDPOINT` was
set to the **full** signal URL:

```
https://otlp-gateway-prod-eu-central-0.grafana.net/otlp/v1/traces
```

That is still correct and safe — `_traces_endpoint()` is idempotent, so the value
works whether or not it carries the `/v1/traces` suffix. No action needed, but be
aware the variable does not hold the "canonical" OTLP base URL.

## Regression test

`backend/config/test_otel_export.py::TracesEndpointTests` — base URL gets the path
appended, trailing slash tolerated, already-full URL left unchanged.
