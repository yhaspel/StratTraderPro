"""Strategies — placeholder views (M02 scaffold).

Real strategy CRUD lands in M03. M02 only needs an MFA-protected URL to
wire the gate.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced


class StrategiesPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "strategies", "status": "ok"}})
