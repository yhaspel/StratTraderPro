"""StratTraderPro URL Configuration."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.orders.views import FillListView, PositionListView, ReconEventListView
from apps.webhooks.views import WebhookView
from config.settings.base import GIT_SHA


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

    # Admin
    path("admin/", admin.site.urls),

    # OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Prometheus metrics
    path("", include("django_prometheus.urls")),

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
    path("api/v1/strategies/", include("apps.strategies.urls")),
    path("api/v1/regime/", include("apps.regime.urls")),
    path("api/v1/sentiment/", include("apps.sentiment.urls")),
    path("api/v1/backtest/", include("apps.backtest.urls")),
    # M10 — admin portal (staff-only; different path space than Django admin at /admin/).
    path("api/v1/admin/", include("apps.admin_portal.urls")),
]
