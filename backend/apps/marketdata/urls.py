"""Marketdata URLs — mounted at /api/v1/marketdata/ (ADR-062)."""
from django.urls import path

from .views import DataProviderKeyDetailView, DataProviderKeysView

urlpatterns = [
    path("keys/", DataProviderKeysView.as_view(), name="marketdata-keys"),
    path("keys/<str:provider>/", DataProviderKeyDetailView.as_view(), name="marketdata-key-detail"),
]
