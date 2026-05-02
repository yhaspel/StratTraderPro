from django.urls import path

from .views import OrdersPingView

urlpatterns = [
    path("ping/", OrdersPingView.as_view(), name="orders-ping"),
]
