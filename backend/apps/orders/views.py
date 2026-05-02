"""Orders — placeholder views (M02 scaffold).

Real order entry / management ships in M05. Today this exists only as the
MFA-enforcement scaffold so AC-02-6 can be exercised against a live URL.
"""
from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.permissions import IsAuthenticatedAndMFAEnforced


class OrdersPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "orders", "status": "ok"}})
