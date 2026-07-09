"""Request-id middleware (M10 §6.6). Honors an inbound ``X-Request-ID`` else
mints a ULID; stores it in the contextvar, tags Sentry, echoes the response
header."""
from __future__ import annotations

from .request_context import new_request_id, reset_request_id, set_request_id


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.META.get("HTTP_X_REQUEST_ID") or new_request_id()
        token = set_request_id(rid)
        # Tag Sentry with request_id + trace_id so events correlate with logs/traces.
        try:
            from config.otel import tag_sentry_correlation

            tag_sentry_correlation()
        except Exception:  # noqa: BLE001,S110 — Sentry/OTel optional
            pass
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response["X-Request-ID"] = rid
        return response
