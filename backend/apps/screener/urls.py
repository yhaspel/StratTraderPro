"""Screener routes (M16 §6.5).

Mounted at ``/api/v1/strategies/<uuid:strategy_id>/screen/`` — see
``config/urls.py``, where this include sits ABOVE the ``api/v1/strategies/``
include so the literal ``screen/`` segment can never be shadowed.
"""
from django.urls import path
from django_ratelimit.decorators import ratelimit

from .views import (
    ScreenCriteriaView,
    ScreenRunCreateView,
    ScreenRunDetailView,
    ScreenRunListView,
)

# House throttle pattern (RegisterView/LoginView in apps/users/views.py):
# django_ratelimit with block=False, and the view itself turns
# ``request.limited`` into an explicit 429 RATE_LIMITED envelope.
# ``RATELIMIT_ENABLE=False`` in the test settings keeps the suite hermetic; the
# throttle test flips it back on with override_settings.
_screen_create = ratelimit(key="user", rate="10/h", method="POST", block=False)(
    ScreenRunCreateView.as_view()
)

urlpatterns = [
    path("", _screen_create, name="screener-run-create"),
    path("criteria/", ScreenCriteriaView.as_view(), name="screener-criteria"),
    path("runs/", ScreenRunListView.as_view(), name="screener-run-list"),
    path("runs/<uuid:run_id>/", ScreenRunDetailView.as_view(), name="screener-run-detail"),
]
