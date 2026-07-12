"""M10.5 §7.3 / §9 — onboarding status aggregation.

``GET /api/v1/onboarding/status/`` returns four read-only booleans computed
server-side from existing models so the client never guesses which "Getting
started" steps are done. It MUST NOT be MFA-gated: step 0 is *enroll MFA*, which
is unreachable if this endpoint 403s for a non-MFA user (§11). Owner-scoped —
every query filters on ``request.user`` so no cross-user state leaks (§11).
"""
from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from .responses import ok
from .schema import OnboardingStatusEnvelopeSerializer


def compute_onboarding_status(user) -> dict:
    """The four onboarding booleans for ``user`` + a derived ``complete`` flag.

    Order mirrors the frozen four-step checklist (plan frozen decision 3):
    (0) MFA enrolled → (1) broker connected → (2) enabled strategy with its
    webhook secret configured → (3) first paper fill seen.
    """
    from apps.brokers.models import BrokerAccount
    from apps.orders.models import Fill
    from apps.strategies.models import WebhookConfig

    mfa_enrolled = bool(getattr(user, "mfa_enabled", False))
    broker_connected = BrokerAccount.objects.filter(user=user).exists()
    # A WebhookConfig always carries an HMAC secret (secret_encrypted), so an
    # enabled strategy with a config == "strategy enabled + webhook configured".
    strategy_ready = WebhookConfig.objects.filter(
        user=user, strategy__is_enabled=True
    ).exists()
    first_fill_seen = Fill.objects.filter(order__user=user).exists()
    return {
        "mfa_enrolled": mfa_enrolled,
        "broker_connected": broker_connected,
        "strategy_ready": strategy_ready,
        "first_fill_seen": first_fill_seen,
        "complete": mfa_enrolled and broker_connected and strategy_ready and first_fill_seen,
    }


class OnboardingStatusView(APIView):
    """GET the onboarding checklist state. Auth required, but NOT MFA-gated."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="onboarding_status",
        tags=["onboarding"],
        responses={200: OnboardingStatusEnvelopeSerializer},
    )
    def get(self, request):
        return ok(compute_onboarding_status(request.user))
