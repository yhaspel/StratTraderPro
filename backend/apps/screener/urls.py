"""Screener routes (M16 §6.5).

Mounted at ``/api/v1/strategies/<uuid:strategy_id>/screen/`` — see
``config/urls.py``, where this include sits ABOVE the ``api/v1/strategies/``
include so the literal ``screen/`` segment can never be shadowed.

NOTE: the run-create throttle is applied INSIDE the view, not by wrapping
``as_view()`` here. The house pattern (RegisterView / LoginView) wraps the view
because those endpoints throttle on the submitted *email* or the client IP,
both of which are readable at the Django layer. AC-16-8 throttles **per user**,
and this project is JWT-only — ``request.user`` is still ``AnonymousUser`` when
a URL-level decorator runs, because DRF authenticates later. Wrapping here
would key every caller on the same constant, turning a per-user limit into one
global bucket that unauthenticated requests could drain. See
``ScreenRunCreateView.post``.
"""
from django.urls import path

from .views import (
    ScreenCriteriaView,
    ScreenRunCreateView,
    ScreenRunDetailView,
    ScreenRunListView,
)

urlpatterns = [
    path("", ScreenRunCreateView.as_view(), name="screener-run-create"),
    path("criteria/", ScreenCriteriaView.as_view(), name="screener-criteria"),
    path("runs/", ScreenRunListView.as_view(), name="screener-run-list"),
    path("runs/<uuid:run_id>/", ScreenRunDetailView.as_view(), name="screener-run-detail"),
]
