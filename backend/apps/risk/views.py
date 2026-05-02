"""Risk — placeholder views (M02 scaffold).

Risk-config UI ships in M06. M02 only needs an MFA-protected URL to wire
the gate.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced


class RiskPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "risk", "status": "ok"}})
