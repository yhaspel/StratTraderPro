"""Brokers — placeholder views (M02 scaffold).

A real broker-management surface lands in M04. For now we provide a single
``/api/v1/brokers/ping/`` endpoint guarded by MFA enforcement so that
M02's AC-02-6 ("calling /api/v1/brokers/ without MFA returns 403
MFA_REQUIRED") can be verified end-to-end against a live URL.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced


class BrokersPingView(APIView):
    """200 OK iff caller is authenticated AND has MFA enabled."""

    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True  # opt-in for IsAuthenticatedAndMFAEnforced

    def get(self, request):
        return Response({"data": {"app": "brokers", "status": "ok"}})
