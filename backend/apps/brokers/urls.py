from django.urls import path

from .views import BrokersPingView

urlpatterns = [
    path("ping/", BrokersPingView.as_view(), name="brokers-ping"),
]
