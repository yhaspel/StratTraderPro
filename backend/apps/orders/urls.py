"""Orders — URL routes (M04). Mounted under /api/v1/orders/.

/api/v1/positions/ and /api/v1/fills/ are mounted directly in config/urls.py
(they are sibling top-level resources, not nested under orders).
"""
from django.urls import path

from .views import OrderListView, OrdersPingView

urlpatterns = [
    path("", OrderListView.as_view(), name="orders-list"),
    # Kept from the M02 scaffold (MFA-enforcement smoke).
    path("ping/", OrdersPingView.as_view(), name="orders-ping"),
]
