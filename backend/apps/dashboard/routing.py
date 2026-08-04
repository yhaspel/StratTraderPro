"""Channels websocket routing (M04 §6.6)."""
from django.urls import re_path

from .consumers import DashboardConsumer

websocket_urlpatterns = [
    re_path(r"ws/dashboard/$", DashboardConsumer.as_asgi()),
]
