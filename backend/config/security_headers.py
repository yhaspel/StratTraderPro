"""Security-response-header middleware (M11 §7.1 V9 / §4.6).

Adds Content-Security-Policy (REPORT-ONLY by default, frozen decision §4.6) and
Permissions-Policy to Django responses. HSTS / Referrer-Policy /
X-Content-Type-Options are handled by Django's SecurityMiddleware (settings) —
this middleware fills the two gaps Django has no native setting for.

Why report-only: the Django tier serves JSON APIs (CSP is inert for JSON) plus
the drf-spectacular Swagger UI + DRF browsable API, which load scripts/styles a
strict `default-src 'none'` would block under *enforce*. Report-only lets us ship
the policy and observe before flipping. The SPA's own CSP is set by the frontend
nginx (separate concern). Flip to enforce by setting CSP_REPORT_ONLY=false once
the reports are clean.

Settings are read per-request (not cached in __init__) so a config change / test
override takes effect without rebuilding the middleware.
"""
from __future__ import annotations

from django.conf import settings


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "CSP_POLICY", "")
        permissions_policy = getattr(settings, "PERMISSIONS_POLICY", "")
        header = (
            "Content-Security-Policy-Report-Only"
            if getattr(settings, "CSP_REPORT_ONLY", True)
            else "Content-Security-Policy"
        )
        # setdefault semantics — never clobber a view that set its own policy.
        if csp and not response.has_header(header):
            response[header] = csp
        if permissions_policy and not response.has_header("Permissions-Policy"):
            response["Permissions-Policy"] = permissions_policy
        return response
