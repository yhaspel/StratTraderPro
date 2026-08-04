"""Brokers — URL routes (M04). Mounted under /api/v1/brokers/."""
from django.urls import path

from .tradestation.views import TradeStationOAuthCallbackView, TradeStationOAuthStartView
from .views import (
    BrokerDetailView,
    BrokerFlattenView,
    BrokerListCreateView,
    BrokerModeView,
    BrokersPingView,
    BrokerStatusView,
    BrokerTestConnectionView,
)

urlpatterns = [
    path("", BrokerListCreateView.as_view(), name="brokers-list"),
    # Kept from the M02 scaffold (AC-02-6 exercises this URL).
    path("ping/", BrokersPingView.as_view(), name="brokers-ping"),
    # TradeStation OAuth2 (M05 — behind BROKER_TRADESTATION_ENABLED).
    path(
        "tradestation/oauth/start/",
        TradeStationOAuthStartView.as_view(),
        name="brokers-ts-oauth-start",
    ),
    path(
        "tradestation/oauth/callback/",
        TradeStationOAuthCallbackView.as_view(),
        name="brokers-ts-oauth-callback",
    ),
    path("<uuid:pk>/", BrokerDetailView.as_view(), name="brokers-detail"),
    path(
        "<uuid:pk>/test-connection/",
        BrokerTestConnectionView.as_view(),
        name="brokers-test-connection",
    ),
    path("<uuid:pk>/status/", BrokerStatusView.as_view(), name="brokers-status"),
    path("<uuid:pk>/mode/", BrokerModeView.as_view(), name="brokers-mode"),
    path("<uuid:pk>/flatten/", BrokerFlattenView.as_view(), name="brokers-flatten"),
]
