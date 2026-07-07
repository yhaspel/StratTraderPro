"""Broker management API (M04 §9).

    GET    /api/v1/brokers/                     list connected brokers
    POST   /api/v1/brokers/                     connect (alpaca paper) — tests creds
    GET    /api/v1/brokers/{id}/
    DELETE /api/v1/brokers/{id}/                MFA re-prompt; stops stream
    POST   /api/v1/brokers/{id}/test-connection/
    GET    /api/v1/brokers/{id}/status/
    POST   /api/v1/brokers/{id}/flatten/        admin-gated debug in M04

All endpoints are MFA-enforced (M02). Secrets are write-only; connection tests
never return keys. ``BROKER_ALPACA_ENABLED=false`` → connect/flatten 503.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.mfa import verify_mfa_code
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .errors import BrokerError
from .metrics import BROKER_CONNECT_TOTAL
from .models import BrokerAccount
from .serializers import (
    BrokerAccountSerializer,
    BrokerConnectSerializer,
    BrokerRemoveSerializer,
)
from .services import (
    build_adapter,
    build_adapter_from_keys,
    encrypt_key,
    get_stream_status,
    notify_accounts_changed,
)

logger = logging.getLogger(__name__)


def _alpaca_enabled() -> bool:
    return getattr(settings, "BROKER_ALPACA_ENABLED", True)


def _disabled():
    return fail("BROKER_DISABLED", "The broker feature is disabled by ops.", status=503)


# Kept from the M02 scaffold so AC-02-6 (unauthenticated → MFA_REQUIRED) still
# has a stable URL to exercise.
class BrokersPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "brokers", "status": "ok"}})


class BrokerListCreateView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="brokers_list", tags=["brokers"])
    def get(self, request):
        qs = BrokerAccount.objects.filter(user=request.user).order_by("-is_default", "created_at")
        return ok(BrokerAccountSerializer(qs, many=True).data)

    @extend_schema(operation_id="brokers_connect", tags=["brokers"])
    def post(self, request):
        if not _alpaca_enabled():
            return _disabled()
        ser = BrokerConnectSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        data = ser.validated_data

        # Test the creds BEFORE persisting anything (AC-04-6). A live key or a
        # bad key never creates a row.
        try:
            adapter = build_adapter_from_keys(
                api_key_id=data["api_key_id"],
                api_secret=data["api_secret"],
                broker=data["broker"],
            )
            info = adapter.connect()
        except BrokerError as exc:
            BROKER_CONNECT_TOTAL.labels(broker=data["broker"].lower(), result="fail").inc()
            return fail(exc.code, exc.message, status=400)

        # Dedup: same user+broker+account_number already connected?
        if BrokerAccount.objects.filter(
            user=request.user, broker=data["broker"], account_number=info.account_number
        ).exists():
            return fail(
                "BROKER_ALREADY_CONNECTED",
                "This broker account is already connected.",
                status=409,
            )

        make_default = data.get("is_default") or not BrokerAccount.objects.filter(
            user=request.user
        ).exists()
        if make_default:
            BrokerAccount.objects.filter(user=request.user, is_default=True).update(is_default=False)

        account = BrokerAccount.objects.create(
            user=request.user,
            broker=data["broker"],
            mode=data["mode"],
            api_key_id_enc=encrypt_key(data["api_key_id"]),
            api_secret_enc=encrypt_key(data["api_secret"]),
            account_number=info.account_number,
            nickname=data.get("nickname", ""),
            is_default=make_default,
            status=BrokerAccount.Status.CONNECTED,
            last_connected_at=timezone.now(),
        )
        BROKER_CONNECT_TOTAL.labels(broker=data["broker"].lower(), result="ok").inc()
        notify_accounts_changed(account.id, "add")
        body = BrokerAccountSerializer(account).data
        body["buying_power"] = str(info.buying_power)
        return ok(body, status=201)


class BrokerDetailView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def _get(self, request, pk) -> BrokerAccount:
        return get_object_or_404(BrokerAccount, pk=pk, user=request.user)

    @extend_schema(operation_id="brokers_detail", tags=["brokers"])
    def get(self, request, pk):
        account = self._get(request, pk)
        return ok(BrokerAccountSerializer(account).data)

    @extend_schema(operation_id="brokers_remove", tags=["brokers"])
    def delete(self, request, pk):
        account = self._get(request, pk)
        ser = BrokerRemoveSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        if not verify_mfa_code(request.user, ser.validated_data["mfa_code"]):
            return fail("MFA_REQUIRED", "A valid MFA code is required to remove a broker.", status=403)
        account_id = account.id
        was_default = account.is_default
        account.delete()
        notify_accounts_changed(account_id, "remove")
        # Promote another account to default if we removed the default one.
        if was_default:
            nxt = BrokerAccount.objects.filter(user=request.user).order_by("created_at").first()
            if nxt is not None:
                nxt.is_default = True
                nxt.save(update_fields=["is_default"])
        return ok({"id": str(account_id), "removed": True})


class BrokerTestConnectionView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="brokers_test_connection", tags=["brokers"])
    def post(self, request, pk):
        if not _alpaca_enabled():
            return _disabled()
        account = get_object_or_404(BrokerAccount, pk=pk, user=request.user)
        try:
            adapter = build_adapter(account)
            acct = adapter.get_account()
        except BrokerError as exc:
            BrokerAccount.objects.filter(pk=account.pk).update(status=BrokerAccount.Status.ERROR)
            return fail(exc.code, exc.message, status=400)
        BrokerAccount.objects.filter(pk=account.pk).update(
            status=BrokerAccount.Status.CONNECTED, last_connected_at=timezone.now()
        )
        return ok(
            {
                "account_number": acct.account_number,
                "buying_power": str(acct.buying_power),
                "cash": str(acct.cash),
                "currency": acct.currency,
                "status": "CONNECTED",
            }
        )


class BrokerStatusView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="brokers_status", tags=["brokers"])
    def get(self, request, pk):
        account = get_object_or_404(BrokerAccount, pk=pk, user=request.user)
        return ok(
            {
                "id": str(account.id),
                "broker_status": account.status,
                "stream_status": get_stream_status(account),
            }
        )


class BrokerModeView(APIView):
    """PAPER ↔ LIVE mode switch (M05 §6.6 / AC-05-8). LIVE is rejected until the
    global flag is on AND the user has opted in — server-enforced regardless of
    UI. M05 always rejects LIVE (ENABLE_LIVE_TRADING defaults False)."""

    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="brokers_set_mode", tags=["brokers"])
    def post(self, request, pk):
        account = get_object_or_404(BrokerAccount, pk=pk, user=request.user)
        mode = str(request.data.get("mode", "")).upper().strip()
        if mode not in (BrokerAccount.Mode.PAPER, BrokerAccount.Mode.LIVE):
            return fail("VALIDATION_ERROR", "mode must be PAPER or LIVE.", status=400)
        if mode == BrokerAccount.Mode.LIVE:
            enabled = getattr(settings, "ENABLE_LIVE_TRADING", False) and getattr(
                request.user, "live_trading_enabled", False
            )
            if not enabled:
                return fail(
                    "LIVE_TRADING_DISABLED",
                    "Live trading is not available yet.",
                    status=403,
                )
        account.mode = mode
        account.save(update_fields=["mode", "updated_at"])
        return ok({"id": str(account.id), "mode": account.mode})


class BrokerFlattenView(APIView):
    """Admin-gated debug flatten in M04 (full kill-switch engine in M08)."""

    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="brokers_flatten", tags=["brokers"])
    def post(self, request, pk):
        if not _alpaca_enabled():
            return _disabled()
        if not request.user.is_staff:
            return fail("FORBIDDEN", "Flatten is admin-gated in M04.", status=403)
        account = get_object_or_404(BrokerAccount, pk=pk, user=request.user)
        reason = str(request.data.get("reason", "manual_flatten"))[:64]
        try:
            adapter = build_adapter(account)
            acks = adapter.flatten_all(reason)
            from apps.orders.services import reconcile_positions

            reconcile_positions(account, adapter)
        except BrokerError as exc:
            return fail(exc.code, exc.message, status=400)
        logger.info("broker.flatten", extra={"account": str(account.id), "reason": reason})
        return ok({"flattened": len(acks), "reason": reason})
