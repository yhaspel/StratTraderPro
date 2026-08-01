"""StratTraderPro URL Configuration."""
from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework import permissions

from apps.admin_portal.permissions import IsAdminAndMFAEnforced
from apps.orders.views import FillListView, PositionListView, ReconEventListView
from apps.webhooks.views import WebhookView
from config.settings.base import GIT_SHA

# P3-5: OpenAPI schema + Swagger UI are admin-only in prod, open in DEBUG.
_schema_perms = [permissions.AllowAny] if settings.DEBUG else [IsAdminAndMFAEnforced]


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------
def healthz(request):
    """Liveness probe — always returns 200 if the process is running."""
    return JsonResponse({"status": "ok", "version": GIT_SHA})


def readyz(request):
    """Readiness probe — checks Postgres and Redis connectivity."""
    checks = {}

    # Check database
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"

    # Check Redis
    try:
        from django.core.cache import cache
        cache.set("readyz_probe", "1", timeout=5)
        if cache.get("readyz_probe") == "1":
            checks["redis"] = "ok"
        else:
            checks["redis"] = "error: read-back failed"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status=200 if all_ok else 503,
    )


# ---------------------------------------------------------------------------
# URL patterns
# ---------------------------------------------------------------------------
urlpatterns = [
    # Health
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),

    # OpenAPI — P3-5: full API-surface disclosure is admin-only in prod (open in
    # DEBUG for local dev). The schema-export pipeline reads the code, not this
    # endpoint, so gating it doesn't affect type generation.
    path("api/schema/", SpectacularAPIView.as_view(permission_classes=_schema_perms), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema", permission_classes=_schema_perms),
        name="swagger-ui",
    ),

    # M10 §6.5a — /metrics is now served OUTSIDE the urlconf by
    # config/metrics_endpoint.py (wired into config/wsgi.py + config/asgi.py) so
    # scrapes bypass the middleware chain. The django_prometheus.urls include was
    # removed here; its middlewares + DB engine wrappers stay (they PRODUCE the
    # series). Rollback = re-add `path("", include("django_prometheus.urls"))`.

    # M04 — public webhook receiver. Mounted OUTSIDE /api/v1 so no JWT auth
    # middleware runs; the in-body `sig` secret is the only credential (ADR-042).
    path(
        "hooks/v1/<uuid:user_id>/<uuid:strategy_id>/",
        WebhookView.as_view(),
        name="webhook-ingest",
    ),

    # API v1
    path("api/v1/", include("apps.users.urls")),
    path("api/v1/brokers/", include("apps.brokers.urls")),
    path("api/v1/orders/", include("apps.orders.urls")),
    path("api/v1/positions/", PositionListView.as_view(), name="positions-list"),
    path("api/v1/fills/", FillListView.as_view(), name="fills-list"),
    path("api/v1/reconciliation/events/", ReconEventListView.as_view(), name="reconciliation-events"),
    path("api/v1/risk/", include("apps.risk.urls")),
    path("api/v1/marketdata/", include("apps.marketdata.urls")),
    path("api/v1/strategies/", include("apps.strategies.urls")),
    path("api/v1/regime/", include("apps.regime.urls")),
    path("api/v1/sentiment/", include("apps.sentiment.urls")),
    path("api/v1/backtest/", include("apps.backtest.urls")),
    # M10 — admin portal (staff-only; different path space than Django admin at /admin/).
    path("api/v1/admin/", include("apps.admin_portal.urls")),
]


# ---------------------------------------------------------------------------
# H8 — Django's stock /admin/ is an unthrottled staff-password surface (session
# auth, no MFA, no lockout, editable is_staff/is_superuser) that bypasses the
# M10 IsAdminAndMFAEnforced design. Mount it ONLY in DEBUG (local dev); in prod
# rely on the /api/v1/admin/ portal. Unmounting means /admin/login/ 404s in prod
# rather than accepting credentials.
# ---------------------------------------------------------------------------
if settings.DEBUG:
    urlpatterns.insert(2, path("admin/", admin.site.urls))
