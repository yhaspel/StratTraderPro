"""M03 — Strategies & Webhook Config views.

Endpoints (plan §6.3):
    GET    /api/v1/strategies/                              list
    POST   /api/v1/strategies/                              upload (multipart)
    GET    /api/v1/strategies/{id}/                         detail
    PATCH  /api/v1/strategies/{id}/                         rename / toggle
    DELETE /api/v1/strategies/{id}/                         soft-delete (user)
    GET    /api/v1/strategies/{id}/files/{kind}/            download bytes
    GET    /api/v1/strategies/{id}/webhook-config/          read schema + url
    PUT    /api/v1/strategies/{id}/webhook-config/          update schema + template
    POST   /api/v1/strategies/{id}/webhook-config/rotate/   rotate secret (reveal-once)
    GET    /api/v1/strategies/{id}/webhook-config/url/      reveal current URL + secret (single-use)
    POST   /api/v1/strategies/{id}/webhook-config/dry-run/  validate a payload against the schema

All endpoints require auth + MFA per M02. STRATEGIES_V1_ENABLED feature
flag returns 503 when off (AC-03-12 + plan §15).
"""
from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.audit.events import AuditEventType
from apps.audit.services import emit
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from . import services
from .metrics import (
    STRATEGY_UPLOADS_TOTAL,
    STRATEGY_WEBHOOK_ROTATIONS_TOTAL,
    StrategyUploadResult,
    refresh_count_gauge,
)
from .models import Strategy, StrategyFile
from .permissions import can_user_delete, can_user_modify, can_user_view
from .serializers import (
    StrategySerializer,
    StrategyUpdateSerializer,
    StrategyUploadSerializer,
    WebhookConfigReadSerializer,
    WebhookConfigUpdateSerializer,
    WebhookDryRunSerializer,
)
from .validators import (
    StrategyValidationError,
    validate_json_schema,
    validate_payload_against_schema,
    validate_uploaded_bundle,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------
def _feature_disabled():
    return fail(
        "FEATURE_DISABLED",
        "The strategies feature is currently disabled by ops.",
        status=503,
    )


def _enabled() -> bool:
    return getattr(settings, "STRATEGIES_V1_ENABLED", True)


def _visible_qs(user):
    """List queryset: own strategies + all system strategies. Defaults to
    is_enabled=True; the caller can apply ``include_disabled`` from the
    query string if needed."""
    return (
        Strategy.objects.filter(is_enabled=True)
        .filter(_owner_or_system_q(user))
        .order_by("is_system", "name")
    )


def _owner_or_system_q(user):
    from django.db.models import Q
    return Q(is_system=True) | Q(owner=user)


def _detail_qs(user):
    """For show / edit / delete — bypass is_enabled filter so users can
    view their own soft-deleted ones."""
    return Strategy.objects.filter(_owner_or_system_q(user))


def _make_unique_slug(user, base: str) -> str:
    """Produce a slug unique within (user, slug). System strategies use
    NULL owner so per-user uniqueness only applies to user uploads."""
    base = slugify(base)[:60] or "strategy"
    candidate = base
    n = 2
    qs = Strategy.objects.filter(owner=user)
    while qs.filter(slug=candidate).exists():
        suffix = f"-{n}"
        candidate = f"{base[: 64 - len(suffix)]}{suffix}"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# Strategies — list + upload
# ---------------------------------------------------------------------------
class StrategiesListCreateView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True
    parser_classes = []  # populated below

    def get_parsers(self):
        from rest_framework.parsers import JSONParser, MultiPartParser
        return [JSONParser(), MultiPartParser()]

    @extend_schema(operation_id="strategies_list", tags=["strategies"])
    def get(self, request):
        if not _enabled():
            return _feature_disabled()
        qs = _visible_qs(request.user).select_related("owner").prefetch_related("files")
        ser = StrategySerializer(qs, many=True, context={"request": request})
        return ok(ser.data)

    @extend_schema(
        operation_id="strategies_upload",
        tags=["strategies"],
        summary="Upload a 3-file strategy bundle.",
    )
    def post(self, request):
        if not _enabled():
            return _feature_disabled()

        ser = StrategyUploadSerializer(data=request.data)
        if not ser.is_valid():
            STRATEGY_UPLOADS_TOTAL.labels(result=StrategyUploadResult.REJECTED).inc()
            return fail(
                "VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors,
            )

        # Pull the three files out of multipart. The frontend wizard sends
        # them under fixed field names.
        files = request.FILES
        try:
            bundle_input = {
                "pine": (files["pine"].name, files["pine"].read()),
                "description": (files["description"].name, files["description"].read()),
                "webhook": (files["webhook"].name, files["webhook"].read()),
            }
        except KeyError as exc:
            STRATEGY_UPLOADS_TOTAL.labels(result=StrategyUploadResult.REJECTED).inc()
            return fail(
                "STRATEGY_FILE_MISMATCH",
                f"Missing file part {exc.args[0]!r}. Expected pine, description, webhook.",
                status=400,
            )

        try:
            parsed = validate_uploaded_bundle(bundle_input)
        except StrategyValidationError as exc:
            STRATEGY_UPLOADS_TOTAL.labels(result=StrategyUploadResult.REJECTED).inc()
            return fail(exc.code, exc.message, status=400, details=exc.details)

        # Slug + duplicate check.
        slug = _make_unique_slug(request.user, parsed.stem)
        # Friendly display name from the stem.
        display_name = parsed.stem.replace("_", " ").replace("-", " ").strip() or slug

        try:
            strategy = Strategy.objects.create(
                owner=request.user,
                name=display_name[:64],
                slug=slug,
                description_short="User-uploaded strategy. Untested.",
                is_system=False,
                is_enabled=True,
                is_community_tested=False,
            )
            for kind, fname, blob, digest in (
                (StrategyFile.Kind.PINE, parsed.pine_filename, parsed.pine_bytes, parsed.pine_sha256),
                (StrategyFile.Kind.DESC, parsed.desc_filename, parsed.desc_bytes, parsed.desc_sha256),
                (
                    StrategyFile.Kind.WEBHOOK_TEMPLATE,
                    parsed.webhook_filename,
                    parsed.webhook_bytes,
                    parsed.webhook_sha256,
                ),
            ):
                StrategyFile.objects.create(
                    strategy=strategy,
                    kind=kind,
                    filename=fname[:128],
                    sha256=digest,
                    content=bytes(blob),
                    size_bytes=len(blob),
                )
        except Exception:  # pragma: no cover — defensive
            STRATEGY_UPLOADS_TOTAL.labels(result=StrategyUploadResult.ERROR).inc()
            logger.exception("strategy.upload.error")
            return fail("STRATEGY_WEBHOOK_INVALID", "Failed to persist strategy.", status=500)

        STRATEGY_UPLOADS_TOTAL.labels(result=StrategyUploadResult.OK).inc()
        refresh_count_gauge()
        emit(
            AuditEventType.STRATEGY_CREATED,
            user=request.user,
            actor=request.user,
            request=request,
            entity_type="strategy",
            entity_id=strategy.id,
            data_after={"name": display_name, "slug": slug},
        )
        logger.info(
            "strategy.upload.ok",
            extra={"user": str(request.user.id), "slug": slug},
        )
        out = StrategySerializer(strategy, context={"request": request}).data
        return ok(out, status=201)


# ---------------------------------------------------------------------------
# Strategy detail / patch / soft-delete
# ---------------------------------------------------------------------------
class StrategyDetailView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="strategies_detail", tags=["strategies"])
    def get(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = get_object_or_404(_detail_qs(request.user).prefetch_related("files"), pk=pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        return ok(StrategySerializer(strategy, context={"request": request}).data)

    @extend_schema(operation_id="strategies_update", tags=["strategies"])
    def patch(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = get_object_or_404(_detail_qs(request.user), pk=pk)
        if not can_user_modify(request.user, strategy):
            # System strategies — only `is_enabled` is settable, and only via
            # PATCH from a user (which sets *their own* preference; today we
            # don't model per-user system enable/disable so the semantics is
            # "system rows: only staff can edit").
            return fail(
                "STRATEGY_SYSTEM_IMMUTABLE",
                "System strategies cannot be modified.",
                status=403,
            )
        ser = StrategyUpdateSerializer(strategy, data=request.data, partial=True)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        ser.save()
        return ok(StrategySerializer(strategy, context={"request": request}).data)

    @extend_schema(operation_id="strategies_delete", tags=["strategies"])
    def delete(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = get_object_or_404(_detail_qs(request.user), pk=pk)
        if not can_user_delete(request.user, strategy):
            return fail(
                "STRATEGY_SYSTEM_IMMUTABLE",
                "System strategies cannot be deleted.",
                status=403,
            )
        # Soft-delete = is_enabled=False. Hard delete is admin-only.
        strategy.is_enabled = False
        strategy.save(update_fields=["is_enabled", "updated_at"])
        refresh_count_gauge()
        return ok({"id": str(strategy.id), "is_enabled": False})


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------
class StrategyFileDownloadView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="strategies_file_download", tags=["strategies"])
    def get(self, request, pk, kind):
        if not _enabled():
            return _feature_disabled()
        kind = kind.upper()
        if kind not in dict(StrategyFile.Kind.choices):
            return fail("STRATEGY_NOT_FOUND", f"Unknown file kind {kind!r}.", status=404)
        strategy = get_object_or_404(_detail_qs(request.user), pk=pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        sf = strategy.files.filter(kind=kind).first()
        if not sf or not sf.content:
            return fail("STRATEGY_NOT_FOUND", "File not found.", status=404)
        ctype = {
            "PINE": "text/plain; charset=utf-8",
            "DESC": "text/plain; charset=utf-8",
            "WEBHOOK_TEMPLATE": "application/json",
        }.get(kind, "application/octet-stream")
        return HttpResponse(bytes(sf.content), content_type=ctype)


# ---------------------------------------------------------------------------
# Webhook config — read / update / rotate / url / dry-run
# ---------------------------------------------------------------------------
class WebhookConfigView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    def _load_strategy(self, request, pk) -> Optional[Strategy]:
        return get_object_or_404(_detail_qs(request.user), pk=pk)

    @extend_schema(operation_id="strategies_webhook_get", tags=["strategies"])
    def get(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = self._load_strategy(request, pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        cfg, created, raw_secret = services.get_or_create_webhook_config(
            user=request.user, strategy=strategy,
        )
        body = WebhookConfigReadSerializer(cfg).data
        # Reveal-once: first-time creation surfaces the secret here. Subsequent
        # gets do NOT include the secret — caller must use /rotate/ to reveal
        # a new one.
        if created and raw_secret is not None:
            body["secret"] = raw_secret
            body["reveal_once"] = True
        else:
            body["secret"] = None
            body["reveal_once"] = False
        return ok(body)

    @extend_schema(operation_id="strategies_webhook_update", tags=["strategies"])
    def put(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = self._load_strategy(request, pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        ser = WebhookConfigUpdateSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        try:
            validate_json_schema(ser.validated_data["json_schema"])
            validate_payload_against_schema(
                ser.validated_data["payload_template"],
                ser.validated_data["json_schema"],
            )
        except StrategyValidationError as exc:
            return fail(exc.code, exc.message, status=400, details=exc.details)

        cfg, _created, _raw = services.get_or_create_webhook_config(
            user=request.user, strategy=strategy,
        )
        cfg.json_schema = ser.validated_data["json_schema"]
        cfg.payload_template = ser.validated_data["payload_template"]
        cfg.save(update_fields=["json_schema", "payload_template", "updated_at"])
        return ok(WebhookConfigReadSerializer(cfg).data)


class WebhookConfigRotateView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="strategies_webhook_rotate", tags=["strategies"])
    def post(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = get_object_or_404(_detail_qs(request.user), pk=pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        cfg, _created, _raw = services.get_or_create_webhook_config(
            user=request.user, strategy=strategy,
        )
        result = services.rotate_secret(config=cfg)
        STRATEGY_WEBHOOK_ROTATIONS_TOTAL.inc()
        logger.info(
            "strategy.webhook.rotate",
            extra={"user": str(request.user.id), "strategy": str(strategy.id), "version": cfg.version},
        )
        return ok({
            "url": result.url,
            "secret": result.new_secret,        # reveal-once
            "version": result.config.version,
            "rotated_at": result.config.rotated_at,
            "reveal_once": True,
        })


class WebhookConfigDryRunView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="strategies_webhook_dryrun", tags=["strategies"])
    def post(self, request, pk):
        if not _enabled():
            return _feature_disabled()
        strategy = get_object_or_404(_detail_qs(request.user), pk=pk)
        if not can_user_view(request.user, strategy):
            return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)
        cfg, _created, _raw = services.get_or_create_webhook_config(
            user=request.user, strategy=strategy,
        )
        ser = WebhookDryRunSerializer(data=request.data)
        if not ser.is_valid():
            return fail("VALIDATION_ERROR", "Invalid input.", status=400, details=ser.errors)
        try:
            validate_payload_against_schema(ser.validated_data["payload"], cfg.json_schema)
        except StrategyValidationError as exc:
            return fail(exc.code, exc.message, status=400, details=exc.details)
        return ok({"valid": True})
