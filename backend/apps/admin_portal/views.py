"""Admin-portal API (M10 §6.2). All routes under /api/v1/admin/, gated by
``IsAdminAndMFAEnforced`` + the env-only ``ADMIN_PORTAL_ENABLED`` master flag.
Sensitive mutations (⚿) additionally require a fresh ``mfa_code``.
"""
from __future__ import annotations

import csv
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.audit.events import AuditEventType
from apps.audit.i18n import COLUMNS, get_labels
from apps.audit.models import AuditLog
from apps.audit.services import emit
from apps.brokers.models import BrokerAccount, TradingHalt
from apps.risk import killswitch
from apps.users.mfa import verify_mfa_code
from apps.users.responses import fail, ok

from . import flags
from .health import collect_health
from .impersonation import start_session, stop_session
from .models import ImpersonationSession
from .permissions import IsAdminAndMFAEnforced
from .serializers import (
    AdminUserListSerializer,
    AuditLogSerializer,
    FlagFlipSerializer,
    KillswitchSerializer,
    MfaReasonSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()

HALT_CONFIRM_PHRASE = "HALT PLATFORM"  # server-validated; intentionally not translated (§11)
_MAX_EXPORT = 100_000
_PAGE_SIZE = 25


def _csv_safe(value):
    """Neutralize spreadsheet formula injection (orders precedent)."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s


def _paginated(items, *, page, page_size, total):
    total_pages = (total + page_size - 1) // page_size if page_size else 1
    return {"data": items, "meta": {"page": page, "page_size": page_size, "total": total, "total_pages": total_pages}}


def _page_num(request) -> int:
    try:
        return max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        return 1


def _check_mfa(request, code):
    return verify_mfa_code(request.user, code)


class AdminBaseView(APIView):
    permission_classes = [IsAdminAndMFAEnforced]

    def dispatch(self, request, *args, **kwargs):
        if not getattr(settings, "ADMIN_PORTAL_ENABLED", True):
            return JsonResponse(
                {"error": {"code": "ADMIN_PORTAL_DISABLED", "message": "Admin portal is disabled."}},
                status=503,
            )
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class AdminUserListView(AdminBaseView):
    @extend_schema(operation_id="admin_users_list", tags=["admin"])
    def get(self, request):
        qs = User.objects.all().order_by("-created_at")
        q = request.query_params.get("q")
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(email__icontains=q) | Q(display_name__icontains=q))
        is_active = request.query_params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))
        if request.query_params.get("has_broker") == "true":
            qs = qs.filter(id__in=BrokerAccount.objects.values_list("user_id", flat=True))

        total = qs.count()
        page = _page_num(request)
        start = (page - 1) * _PAGE_SIZE
        rows = list(qs[start:start + _PAGE_SIZE])
        broker_counts = dict(_broker_counts(rows))
        data = AdminUserListSerializer(
            [_user_row(u, broker_counts.get(u.id, 0)) for u in rows], many=True
        ).data
        return _envelope(_paginated(data, page=page, page_size=_PAGE_SIZE, total=total))


def _broker_counts(users):
    from django.db.models import Count

    ids = [u.id for u in users]
    rows = (
        BrokerAccount.objects.filter(user_id__in=ids)
        .values("user_id")
        .annotate(c=Count("id"))
    )
    return [(r["user_id"], r["c"]) for r in rows]


def _user_row(u, broker_count):
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "is_active": u.is_active,
        "is_staff": u.is_staff,
        "is_verified": u.is_verified,
        "mfa_enabled": u.mfa_enabled,
        "created_at": u.created_at,
        "broker_count": broker_count,
    }


def _envelope(payload):
    from rest_framework.response import Response

    return Response(payload)


class AdminUserDetailView(AdminBaseView):
    @extend_schema(operation_id="admin_users_detail", tags=["admin"])
    def get(self, request, user_id):
        u = get_object_or_404(User, id=user_id)
        brokers = [
            {
                "id": str(b.id),
                "broker": b.broker,
                "mode": b.mode,
                "status": b.status,
                "account_number": (b.account_number or "")[-4:],
                "is_default": b.is_default,
            }
            for b in BrokerAccount.objects.filter(user=u)
        ]
        recent = AuditLogSerializer(
            AuditLog.objects.filter(user=u).order_by("-id")[:20], many=True
        ).data
        return ok(
            {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
                "is_active": u.is_active,
                "is_staff": u.is_staff,
                "is_verified": u.is_verified,
                "mfa_enabled": u.mfa_enabled,
                "created_at": u.created_at,
                "brokers": brokers,
                "recent_audit": recent,
            }
        )


class AdminUserDisableView(AdminBaseView):
    def post(self, request, user_id):
        return _set_active(request, user_id, active=False)


class AdminUserEnableView(AdminBaseView):
    def post(self, request, user_id):
        return _set_active(request, user_id, active=True)


def _set_active(request, user_id, *, active):
    ser = MfaReasonSerializer(data=request.data)
    if not ser.is_valid():
        return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
    if not _check_mfa(request, ser.validated_data["mfa_code"]):
        return fail("MFA_REQUIRED", "A valid MFA code is required.", status=403)
    u = get_object_or_404(User, id=user_id)
    before = u.is_active
    u.is_active = active
    u.save(update_fields=["is_active"])
    revoked = 0
    if not active:
        from apps.users.services import revoke_other_sessions

        revoked = revoke_other_sessions(u, reason="admin_disable")
    emit(
        AuditEventType.ADMIN_USER_ENABLED if active else AuditEventType.ADMIN_USER_DISABLED,
        actor=request.user,
        user=u,
        request=request,
        entity_type="user",
        entity_id=str(u.id),
        data_before={"is_active": before},
        data_after={"is_active": active, "reason": ser.validated_data["reason"], "families_revoked": revoked},
    )
    note = None if active else (
        "Open positions are NOT auto-flattened; engage an L1 halt with flatten if needed."
    )
    return ok({"id": str(u.id), "is_active": active, "families_revoked": revoked, "note": note})


class AdminImpersonateStartView(AdminBaseView):
    def post(self, request, user_id):
        ser = MfaReasonSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        if not _check_mfa(request, ser.validated_data["mfa_code"]):
            return fail("MFA_REQUIRED", "A valid MFA code is required.", status=403)
        target = get_object_or_404(User, id=user_id)
        if target.id == request.user.id:
            return fail("VALIDATION_ERROR", "Cannot impersonate yourself.", status=400)
        session, token = start_session(
            actor=request.user, target=target, reason=ser.validated_data["reason"], request=request
        )
        return ok({"token": token, "session_id": str(session.id), "expires_at": session.expires_at})


class AdminImpersonationStopView(AdminBaseView):
    def post(self, request, session_id):
        session = get_object_or_404(ImpersonationSession, id=session_id)
        stopped = stop_session(session, actor=request.user, request=request)
        return ok({"session_id": str(session.id), "stopped": stopped, "ended_at": session.ended_at})


# ---------------------------------------------------------------------------
# Audit search + export
# ---------------------------------------------------------------------------
def _audit_qs(request):
    qs = AuditLog.objects.all().order_by("-id")
    p = request.query_params
    if p.get("user"):
        qs = qs.filter(user_id=p["user"])
    if p.get("actor"):
        qs = qs.filter(actor_id=p["actor"])
    if p.get("event_type"):
        qs = qs.filter(event_type=p["event_type"])
    if p.get("entity_type"):
        qs = qs.filter(entity_type=p["entity_type"])
    if p.get("entity_id"):
        qs = qs.filter(entity_id=p["entity_id"])
    if p.get("occurred_after"):
        dt = parse_datetime(p["occurred_after"])
        if dt:
            qs = qs.filter(occurred_at__gte=dt)
    if p.get("occurred_before"):
        dt = parse_datetime(p["occurred_before"])
        if dt:
            qs = qs.filter(occurred_at__lte=dt)
    return qs


class AuditSearchView(AdminBaseView):
    def get(self, request):
        qs = _audit_qs(request)
        total = qs.count()
        page = _page_num(request)
        start = (page - 1) * _PAGE_SIZE
        data = AuditLogSerializer(qs[start:start + _PAGE_SIZE], many=True).data
        return _envelope(_paginated(data, page=page, page_size=_PAGE_SIZE, total=total))


class AuditExportView(AdminBaseView):
    def get(self, request):
        qs = _audit_qs(request)[:_MAX_EXPORT].iterator()
        lang = _admin_language(request.user)
        labels = get_labels(lang)

        def rows():
            buff = _Echo()
            yield buff.write([labels.get(c, c) for c in COLUMNS])
            for r in qs:
                yield buff.write([
                    r.occurred_at.isoformat() if r.occurred_at else "",
                    r.event_type,
                    str(r.user_id) if r.user_id else "",
                    "", str(r.actor_id) if r.actor_id else "", "",
                    _csv_safe(r.entity_type), _csv_safe(r.entity_id),
                    r.ip or "", _csv_safe(r.ua),
                    _csv_safe(r.data_before), _csv_safe(r.data_after),
                    r.self_hash,
                ])

        resp = StreamingHttpResponse(rows(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="audit.csv"'
        return resp


class _Echo:
    def write(self, row):
        import io

        buff = io.StringIO()
        csv.writer(buff).writerow(row)
        return buff.getvalue()


def _admin_language(user) -> str:
    try:
        return user.profile.language or "en"
    except Exception:  # noqa: BLE001
        return "en"


# ---------------------------------------------------------------------------
# Platform kill switch
# ---------------------------------------------------------------------------
class PlatformStatusView(AdminBaseView):
    def get(self, request):
        halt = TradingHalt.objects.filter(level=TradingHalt.Level.L3, released_at__isnull=True).first()
        return ok({
            "platform_halted": halt is not None,
            "halt": None if halt is None else {
                "id": halt.id, "reason": halt.reason, "created_at": halt.created_at,
                "created_by": str(halt.created_by_id) if halt.created_by_id else None,
            },
            "note": "L3 blocks new order intake and does NOT flatten positions.",
        })


class PlatformKillswitchView(AdminBaseView):
    def post(self, request):
        ser = KillswitchSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        data = ser.validated_data
        if not _check_mfa(request, data["mfa_code"]):
            return fail("MFA_REQUIRED", "A valid MFA code is required.", status=403)

        if data["engage"]:
            if data.get("confirm", "") != HALT_CONFIRM_PHRASE:
                return fail("CONFIRM_PHRASE_MISMATCH", f'Type "{HALT_CONFIRM_PHRASE}" to confirm.', status=400)
            halt = killswitch.trigger_halt(
                user_id=None, level=TradingHalt.Level.L3, reason=data["reason"],
                created_by_id=request.user.id,
            )
            emit(
                AuditEventType.ADMIN_PLATFORM_HALT_ENGAGED, actor=request.user, request=request,
                entity_type="trading_halt", entity_id=str(halt.id),
                data_after={"reason": data["reason"], "level": "L3"},
            )
            return ok({"platform_halted": True, "halt_id": halt.id,
                       "note": "L3 blocks new order intake and does NOT flatten positions."})

        halt = TradingHalt.objects.filter(level=TradingHalt.Level.L3, released_at__isnull=True).first()
        if halt is None:
            return ok({"platform_halted": False, "released": False})
        killswitch.release_halt(halt.id, released_by_id=request.user.id)
        emit(
            AuditEventType.ADMIN_PLATFORM_HALT_RELEASED, actor=request.user, request=request,
            entity_type="trading_halt", entity_id=str(halt.id), data_after={"reason": data["reason"]},
        )
        return ok({"platform_halted": False, "released": True})


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
class FlagListView(AdminBaseView):
    def get(self, request):
        return ok(flags.all_flags())


class FlagFlipView(AdminBaseView):
    def post(self, request, name):
        ser = FlagFlipSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        if not _check_mfa(request, ser.validated_data["mfa_code"]):
            return fail("MFA_REQUIRED", "A valid MFA code is required.", status=403)
        try:
            flags.set_flag(
                name, ser.validated_data["enabled"], actor=request.user, request=request,
                note=ser.validated_data.get("note", ""),
            )
        except flags.FlagImmutable:
            return fail("FLAG_IMMUTABLE", "This flag is env-only and cannot be flipped at runtime.", status=400)
        except KeyError:
            return fail("FLAG_UNKNOWN", "Unknown feature flag.", status=404)
        return ok(flags.flag_state(name))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
class AdminHealthView(AdminBaseView):
    def get(self, request):
        return ok(collect_health())
