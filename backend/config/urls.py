"""StratTraderPro URL Configuration."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

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

    # API v1
    path("api/v1/", include("apps.users.urls")),
    # path("api/strategies/", include("apps.strategies.urls")),
    # ...
]
