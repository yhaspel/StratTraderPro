"""Risk — URL routes (M08). Mounted under /api/v1/risk/."""
from django.urls import path

from .views import (
    KillSwitchView,
    RiskEventsView,
    RiskPingView,
    RiskProfileView,
    SizingDecisionsView,
)

urlpatterns = [
    # Kept from the M02 scaffold (AC-02-6 exercises this URL).
    path("ping/", RiskPingView.as_view(), name="risk-ping"),
    path("profile/", RiskProfileView.as_view(), name="risk-profile"),
    path("events/", RiskEventsView.as_view(), name="risk-events"),
    path("sizing-decisions/", SizingDecisionsView.as_view(), name="risk-sizing-decisions"),
    path("killswitches/", KillSwitchView.as_view(), name="risk-killswitches"),
]
