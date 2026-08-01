"""Data-provider key management API (ADR-062).

    GET    /api/v1/marketdata/keys/             both providers' status
    PUT    /api/v1/marketdata/keys/{provider}/  set the instance key (staff)
    DELETE /api/v1/marketdata/keys/{provider}/  remove the UI-stored key (staff)

Reads are MFA-enforced like the rest of the trading surface; writes are
staff-only (``IsAdminAndMFAEnforced``) because the key is instance-wide.
Keys are validated live against the vendor BEFORE persisting (the brokers
AC-04-6 pattern: a bad key never creates a row) and are never echoed back.
"""
from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.admin_portal.permissions import IsAdminAndMFAEnforced
from apps.audit.events import AuditEventType
from apps.audit.services import emit
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from . import keys as keysvc
from .serializers import DataProviderKeySetSerializer

logger = logging.getLogger(__name__)


def _normalize_provider(provider: str) -> str | None:
    p = (provider or "").upper()
    return p if p in keysvc.PROVIDERS else None


def _status_payload(*, staff: bool) -> dict:
    return {
        p.lower(): keysvc.key_status(p, include_admin_detail=staff)
        for p in keysvc.PROVIDERS
    }


class DataProviderKeysView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="marketdata_keys_status", tags=["marketdata"])
    def get(self, request):
        """Status only — ``configured`` + ``source`` for everyone; last-4 hint
        and updated-by detail for staff. Never key material."""
        return ok(_status_payload(staff=bool(request.user.is_staff)))


class DataProviderKeyDetailView(APIView):
    permission_classes = [IsAdminAndMFAEnforced]

    @extend_schema(operation_id="marketdata_keys_set", tags=["marketdata"])
    def put(self, request, provider):
        prov = _normalize_provider(provider)
        if prov is None:
            return fail("UNKNOWN_PROVIDER", "Provider must be FMP or FRED.", status=400)
        ser = DataProviderKeySetSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        raw = ser.validated_data["api_key"]

        # Validate against the vendor BEFORE persisting (AC-04-6 pattern).
        try:
            keysvc.validate_provider_key(prov, raw)
        except keysvc.ProviderKeyInvalid:
            return fail(
                "INVALID_API_KEY",
                f"{prov} rejected this key. Check it and try again.",
                status=400,
            )
        except keysvc.ProviderUnreachable:
            return fail(
                "PROVIDER_UNREACHABLE",
                f"Could not reach {prov} to validate the key. Try again shortly.",
                status=502,
            )

        row = keysvc.set_key(prov, raw, updated_by=request.user)
        emit(
            AuditEventType.DATA_PROVIDER_KEY_SET, user=request.user, actor=request.user,
            request=request, entity_type="data_provider_key", entity_id=prov,
            data_after={"provider": prov, "hint": row.key_hint},
        )
        logger.info("marketdata.provider_key_set", extra={"provider": prov})
        return ok(_status_payload(staff=True))

    @extend_schema(operation_id="marketdata_keys_remove", tags=["marketdata"])
    def delete(self, request, provider):
        prov = _normalize_provider(provider)
        if prov is None:
            return fail("UNKNOWN_PROVIDER", "Provider must be FMP or FRED.", status=400)
        removed = keysvc.clear_key(prov)
        if removed:
            emit(
                AuditEventType.DATA_PROVIDER_KEY_REMOVED, user=request.user, actor=request.user,
                request=request, entity_type="data_provider_key", entity_id=prov,
                data_before={"provider": prov},
            )
            logger.info("marketdata.provider_key_removed", extra={"provider": prov})
        return ok(_status_payload(staff=True))
