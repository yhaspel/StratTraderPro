"""Risk API (M08 §6.1). MFA-enforced; L1/L3 kill-switch triggers MFA-re-prompt."""
from __future__ import annotations

from django.db.models import Q
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.brokers.models import TradingHalt
from apps.users.mfa import verify_mfa_code
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from . import killswitch
from .models import RiskEvent, RiskProfile, SizingDecision
from .serializers import (
    KillSwitchCreateSerializer,
    RiskEventSerializer,
    RiskProfileSerializer,
    SizingDecisionSerializer,
)

_SCOPE_LEVEL = {
    "STRATEGY": TradingHalt.Level.L0,
    "USER": TradingHalt.Level.L1,
    "PLATFORM": TradingHalt.Level.L3,
}


class RiskPingView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def get(self, request):
        return Response({"data": {"app": "risk", "status": "ok"}})


def _get_or_create_profile(user) -> RiskProfile:
    profile, _ = RiskProfile.objects.get_or_create(
        user=user, defaults={"permitted_asset_classes": RiskProfile.default_permitted()}
    )
    return profile


def _profile_for_read(user) -> RiskProfile:
    """RISK-3: return the saved profile, or an UNSAVED default instance for GET.

    A persisted RiskProfile turns sizing ON (integration.apply_sizing keys off
    its existence), so merely *opening* the risk page must not create one. The
    profile is created lazily on the first write (PUT).
    """
    existing = RiskProfile.objects.filter(user=user).first()
    if existing is not None:
        return existing
    return RiskProfile(user=user, permitted_asset_classes=RiskProfile.default_permitted())


class RiskProfileView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="risk_profile_get", tags=["risk"])
    def get(self, request):
        return ok(RiskProfileSerializer(_profile_for_read(request.user)).data)

    @extend_schema(operation_id="risk_profile_put", tags=["risk"])
    def put(self, request):
        profile = _get_or_create_profile(request.user)
        before = RiskProfileSerializer(profile).data
        ser = RiskProfileSerializer(profile, data=request.data, partial=True)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid risk profile.", status=400, details=ser.errors)
        ser.save()
        after = RiskProfileSerializer(profile).data
        from apps.audit.events import AuditEventType
        from apps.audit.services import emit

        changed = {k: after[k] for k in after if before.get(k) != after.get(k)}
        emit(
            AuditEventType.RISK_PROFILE_CHANGED, user=request.user, actor=request.user, request=request,
            entity_type="risk_profile", entity_id=str(profile.id),
            data_before={k: before.get(k) for k in changed}, data_after=changed,
        )
        return ok(after)


class SizingDecisionsView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="risk_sizing_decisions", tags=["risk"])
    def get(self, request):
        qs = SizingDecision.objects.filter(user=request.user).order_by("-created_at")
        if request.query_params.get("order_id"):
            qs = qs.filter(order_id=request.query_params["order_id"])
        return ok(SizingDecisionSerializer(qs[:200], many=True).data)


class RiskEventsView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="risk_events", tags=["risk"])
    def get(self, request):
        qs = RiskEvent.objects.filter(Q(user=request.user) | Q(user__isnull=True)).order_by("-created_at")
        p = request.query_params
        if p.get("type"):
            qs = qs.filter(type=p["type"].upper())
        if p.get("from") and parse_datetime(p["from"]):
            qs = qs.filter(created_at__gte=parse_datetime(p["from"]))
        if p.get("to") and parse_datetime(p["to"]):
            qs = qs.filter(created_at__lte=parse_datetime(p["to"]))
        return ok(RiskEventSerializer(qs[:200], many=True).data)


def _halt_wire(h: TradingHalt) -> dict:
    return {
        "id": str(h.id), "scope": h.scope, "level": h.level, "auto": h.auto,
        "strategy": str(h.strategy_id) if h.strategy_id else None,
        "reason": h.reason, "created_at": h.created_at.isoformat() if h.created_at else None,
    }


class KillSwitchView(APIView):
    """GET active kill switches; POST to trigger/release (AC-08-7/8/9/10)."""

    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="risk_killswitches_list", tags=["risk"])
    def get(self, request):
        halts = TradingHalt.objects.filter(released_at__isnull=True).filter(
            Q(user=request.user) | Q(user__isnull=True)
        ).order_by("-created_at")
        return ok([_halt_wire(h) for h in halts])

    @extend_schema(operation_id="risk_killswitches_set", tags=["risk"])
    def post(self, request):
        ser = KillSwitchCreateSerializer(data=request.data, context={"user": request.user})
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        d = ser.validated_data
        scope, active, level = d["scope"], d["active"], _SCOPE_LEVEL[d["scope"]]

        # MFA re-prompt on the global (L1) + platform (L3) kill switch (§11).
        # Required on BOTH engage and release — releasing a halt is the dangerous
        # direction for a hijacked session (FIX-M14).
        if scope in ("USER", "PLATFORM"):
            if scope == "PLATFORM" and not request.user.is_staff:
                return fail("FORBIDDEN", "Platform kill switch is admin-only.", status=403)
            if not verify_mfa_code(request.user, d.get("mfa_code", "")):
                return fail("MFA_REQUIRED", "A valid MFA code is required for this action.", status=403)

        if active:
            halt = killswitch.trigger_halt(
                user_id=None if scope == "PLATFORM" else request.user.id,
                level=level,
                strategy_id=d.get("target_id") if scope == "STRATEGY" else None,
                reason=d.get("reason", ""),
                created_by_id=request.user.id,
                flatten=d.get("flatten", False) or scope == "USER",
            )
            return ok(_halt_wire(halt), status=201)

        # release
        q = TradingHalt.objects.filter(released_at__isnull=True, level=level)
        if scope == "PLATFORM":
            q = q.filter(user__isnull=True)
        elif scope == "STRATEGY":
            q = q.filter(user=request.user, strategy_id=d.get("target_id"))
        else:
            q = q.filter(user=request.user, strategy__isnull=True)
        halt = q.first()
        if halt is None:
            return ok({"released": False, "detail": "no active halt"})
        released = killswitch.release_halt(halt.id, released_by_id=request.user.id)
        if not released:
            return fail("HALT_LOCKED", "Auto (daily-loss) halts release at the next trading day.", status=409)
        return ok({"released": True, "id": str(halt.id)})
