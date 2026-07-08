"""Backtest URL routes (M09 §6.7). Mounted under /api/v1/backtest/."""
from django.urls import path

from .views import (
    BacktestReportHtmlView,
    BacktestReportJsonView,
    BacktestReportPdfView,
    BacktestRunCancelView,
    BacktestRunDetailView,
    BacktestRunListCreateView,
    BacktestStrategyListView,
)

urlpatterns = [
    path("strategies/", BacktestStrategyListView.as_view(), name="backtest-strategies"),
    path("runs/", BacktestRunListCreateView.as_view(), name="backtest-runs"),
    path("runs/<uuid:pk>/", BacktestRunDetailView.as_view(), name="backtest-run-detail"),
    path("runs/<uuid:pk>/cancel/", BacktestRunCancelView.as_view(), name="backtest-run-cancel"),
    path("runs/<uuid:pk>/report.json", BacktestReportJsonView.as_view(), name="backtest-report-json"),
    path("runs/<uuid:pk>/report.html", BacktestReportHtmlView.as_view(), name="backtest-report-html"),
    path("runs/<uuid:pk>/report.pdf", BacktestReportPdfView.as_view(), name="backtest-report-pdf"),
]
