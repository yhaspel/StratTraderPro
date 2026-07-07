"""Regime — URL routes (M06). Mounted under /api/v1/regime/."""
from django.urls import path

from .views import (
    RegimeCurrentView,
    RegimeHistoryView,
    RegimeModelView,
    RegimeSymbolView,
)

urlpatterns = [
    path("current/", RegimeCurrentView.as_view(), name="regime-current"),
    path("history/", RegimeHistoryView.as_view(), name="regime-history"),
    path("model/", RegimeModelView.as_view(), name="regime-model"),
    path("symbol/<str:sym>/", RegimeSymbolView.as_view(), name="regime-symbol"),
]
