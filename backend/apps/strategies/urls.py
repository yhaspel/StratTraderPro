"""Strategies — URL routes (M03).

Mounted under /api/v1/strategies/ in config/urls.py.
"""
from __future__ import annotations

from django.urls import path

from .views import (
    StrategiesListCreateView,
    StrategyDetailView,
    StrategyFileDownloadView,
    WebhookConfigDryRunView,
    WebhookConfigRotateView,
    WebhookConfigView,
)

urlpatterns = [
    path("", StrategiesListCreateView.as_view(), name="strategies-list"),
    path("<uuid:pk>/", StrategyDetailView.as_view(), name="strategies-detail"),
    path(
        "<uuid:pk>/files/<str:kind>/",
        StrategyFileDownloadView.as_view(),
        name="strategies-file-download",
    ),
    path(
        "<uuid:pk>/webhook-config/",
        WebhookConfigView.as_view(),
        name="strategies-webhook-config",
    ),
    path(
        "<uuid:pk>/webhook-config/rotate/",
        WebhookConfigRotateView.as_view(),
        name="strategies-webhook-rotate",
    ),
    path(
        "<uuid:pk>/webhook-config/dry-run/",
        WebhookConfigDryRunView.as_view(),
        name="strategies-webhook-dry-run",
    ),
]
