from django.urls import path

from .views import StrategiesPingView

urlpatterns = [
    path("ping/", StrategiesPingView.as_view(), name="strategies-ping"),
]
