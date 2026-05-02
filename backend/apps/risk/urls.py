from django.urls import path

from .views import RiskPingView

urlpatterns = [
    path("ping/", RiskPingView.as_view(), name="risk-ping"),
]
