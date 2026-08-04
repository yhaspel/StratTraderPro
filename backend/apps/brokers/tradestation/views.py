"""TradeStation OAuth2 views (M05 §6.1/§9). Behind BROKER_TRADESTATION_ENABLED.

- ``GET /api/v1/brokers/tradestation/oauth/start/`` (JWT+MFA) → consent URL.
- ``GET /api/v1/brokers/tradestation/oauth/callback/`` (public; single-use signed
  state is the auth) → exchanges the code, persists encrypted tokens + accounts,
  redirects to the frontend.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import redirect
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.admin_portal.flags import is_enabled
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from ..errors import BrokerError
from ..metrics import BROKER_CONNECT_TOTAL
from ..models import BrokerAccount
from ..services import encrypt_key
from . import mapping, oauth
from .client import TSClient, exchange_code_for_tokens

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return is_enabled("BROKER_TRADESTATION_ENABLED")


class TradeStationOAuthStartView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        if not _enabled():
            return fail("BROKER_DISABLED", "TradeStation is not enabled.", status=503)
        verifier, challenge = oauth.generate_pkce()
        state = oauth.issue_state(request.user.id)
        oauth.store_verifier(state, verifier)
        return ok({"authorize_url": oauth.build_authorize_url(state=state, code_challenge=challenge)})


class TradeStationOAuthCallbackView(APIView):
    # Public: the browser is redirected here by TradeStation with no JWT. The
    # single-use signed `state` (bound to the user, stored in Redis) is the auth.
    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        frontend = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/settings/brokers"
        if not _enabled():
            return redirect(f"{frontend}?ts=disabled")
        code = request.GET.get("code")
        state = request.GET.get("state", "")
        payload = oauth.consume_state(state)  # single-use
        if not code or payload is None:
            return redirect(f"{frontend}?ts=error&reason=state")
        verifier = oauth.consume_verifier(state)
        try:
            tokens = exchange_code_for_tokens(code, verifier or "")
            client = TSClient(access_token=tokens["access_token"], refresh_token=tokens.get("refresh_token", ""))
            accounts = client.get_accounts()
        except (BrokerError, KeyError, Exception):  # noqa: BLE001 — surface as a UI banner, never 500
            logger.warning("ts.oauth.callback_failed")
            return redirect(f"{frontend}?ts=error&reason=exchange")

        from apps.users.models import User

        try:
            user = User.objects.get(id=payload["user_id"])
        except User.DoesNotExist:  # pragma: no cover
            return redirect(f"{frontend}?ts=error&reason=user")

        created = 0
        for acct in accounts or []:
            acct_dto = mapping.from_ts_account(acct)
            _, was_created = BrokerAccount.objects.update_or_create(
                user=user,
                broker=BrokerAccount.Broker.TRADESTATION,
                account_number=acct_dto.account_number,
                defaults={
                    "mode": BrokerAccount.Mode.PAPER,
                    "ts_access_token_enc": encrypt_key(tokens["access_token"]),
                    "ts_refresh_token_enc": encrypt_key(tokens.get("refresh_token", "")),
                    "ts_scope": tokens.get("scope", ""),
                    "status": BrokerAccount.Status.CONNECTED,
                    "last_connected_at": timezone.now(),
                    "api_key_id_enc": b"",
                    "api_secret_enc": b"",
                },
            )
            created += int(was_created)
        BROKER_CONNECT_TOTAL.labels(broker="tradestation", result="ok").inc()
        return redirect(f"{frontend}?ts=connected&accounts={created}")
