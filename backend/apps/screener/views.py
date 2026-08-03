"""Strategy screener API (M16 §6.5).

Mounted INSIDE the MFA-swept ``strategies`` prefix:
``/api/v1/strategies/{strategy_id}/screen/…``

Every view is ``IsAuthenticatedAndMFAEnforced`` + ``mfa_required`` and resolves
the strategy through the same soft-delete-aware queryset the strategies app
uses, returning **404 STRATEGY_NOT_FOUND** (never 403) for anything the caller
may not see — a 403 would leak that the id exists.
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.admin_portal.flags import is_enabled
from apps.audit.events import AuditEventType
from apps.audit.services import emit
from apps.marketdata.keys import resolve_key
from apps.strategies.models import Strategy, StrategyFile
from apps.strategies.permissions import can_user_view
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .criteria import decode_desc, parse
from .models import ScreenRun
from .serializers import run_detail, run_summary
from .tasks import run_screen

logger = logging.getLogger(__name__)

RUNS_LIST_DEFAULT = 5
RUNS_LIST_MAX = 20


# ---------------------------------------------------------------------------
# Shared gates
# ---------------------------------------------------------------------------
def _enabled() -> bool:
    """Reads through the mutable flag registry so an admin override is honored
    (matches ``apps/strategies/views.py::_enabled``)."""
    return is_enabled("SCREENER_ENABLED")


def _feature_disabled():
    """A3: the house code is ``FEATURE_DISABLED`` + 503 (regime, sentiment and
    strategies all return exactly this). ``SCREENER_DISABLED`` never existed
    anywhere else in the codebase. Applied to EVERY screener endpoint — the
    panel can only hide itself (§6.6 state 1) if the GETs 503 too."""
    return fail("FEATURE_DISABLED", "Strategy screener is disabled.", status=503)


def _load_strategy(request, strategy_id):
    """Soft-delete-aware lookup + visibility check, or ``None``."""
    strategy = get_object_or_404(
        Strategy.objects.filter(deleted_at__isnull=True), pk=strategy_id,
    )
    if not can_user_view(request.user, strategy):
        return None
    return strategy


def _not_found():
    return fail("STRATEGY_NOT_FOUND", "Strategy not found.", status=404)


def _desc_file(strategy):
    return strategy.files.filter(kind=StrategyFile.Kind.DESC).first()


# ---------------------------------------------------------------------------
# GET …/screen/criteria/
# ---------------------------------------------------------------------------
class ScreenCriteriaView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(
        operation_id="screener_criteria",
        tags=["screener"],
        summary="Parse the strategy description's [screen] block.",
    )
    def get(self, request, strategy_id):
        if not _enabled():
            return _feature_disabled()
        strategy = _load_strategy(request, strategy_id)
        if strategy is None:
            return _not_found()

        sf = _desc_file(strategy)
        criteria, errors = parse(decode_desc(sf.content) if sf else "")
        if errors:
            return fail(
                "SCREEN_CRITERIA_INVALID",
                "The [screen] block could not be parsed.",
                status=400,
                details=errors,
            )
        if criteria is None:
            return ok({"block_present": False})
        return ok({
            "block_present": True,
            "criteria": criteria.criteria,
            "fmp_params": criteria.vendor_params,
            "derived": criteria.derived,
        })


# ---------------------------------------------------------------------------
# POST …/screen/
# ---------------------------------------------------------------------------
class ScreenRunCreateView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(
        operation_id="screener_run_create",
        tags=["screener"],
        summary="Queue a screen for this strategy.",
    )
    def post(self, request, strategy_id):
        # Gate order per §6.5 (flag -> throttle -> visibility -> key -> block ->
        # parse -> active-run), each returning its own code.
        if not _enabled():
            return _feature_disabled()
        if getattr(request, "limited", False):
            return fail("RATE_LIMITED", "Too many screen runs. Try again later.", status=429)

        strategy = _load_strategy(request, strategy_id)
        if strategy is None:
            return _not_found()

        # Never read settings.FMP_API_KEY directly — resolve_key is the single
        # UI-key -> env -> unconfigured choke point (ADR-062).
        if not resolve_key("FMP"):
            return fail(
                "FMP_NOT_CONFIGURED",
                "No FMP API key is configured for this instance.",
                status=409,
            )

        sf = _desc_file(strategy)
        criteria, errors = parse(decode_desc(sf.content) if sf else "")
        if errors:
            return fail(
                "SCREEN_CRITERIA_INVALID",
                "The [screen] block could not be parsed.",
                status=400,
                details=errors,
            )
        if criteria is None:
            return fail(
                "NO_SCREEN_CRITERIA",
                "This strategy's description has no [screen] block.",
                status=409,
            )

        active = ScreenRun.objects.filter(
            user=request.user, strategy=strategy, status__in=ScreenRun.ACTIVE_STATUSES,
        ).exists()
        if active:
            return fail("SCREEN_RUN_ACTIVE", "A screen is already running.", status=409)

        snapshot = {
            "criteria": criteria.criteria,
            "fmp_params": criteria.vendor_params,
            "derived": criteria.derived,
            "limit": criteria.limit,
        }
        try:
            # The pre-check above loses a race between two concurrent POSTs; the
            # partial unique index is the real guard and lands here as the SAME
            # 409. atomic() keeps the failed INSERT from poisoning the outer
            # transaction on Postgres.
            with transaction.atomic():
                run = ScreenRun.objects.create(
                    user=request.user,
                    strategy=strategy,
                    criteria=snapshot,
                    desc_sha256=sf.sha256 if sf else "",
                )
        except IntegrityError:
            return fail("SCREEN_RUN_ACTIVE", "A screen is already running.", status=409)

        run_screen.delay(str(run.id))
        emit(
            AuditEventType.SCREEN_RUN_REQUESTED,
            user=request.user, actor=request.user, request=request,
            entity_type="strategy", entity_id=str(strategy.id),
            # No criteria payload — the run row IS the record (§11).
            data_after={"run_id": str(run.id)},
        )
        logger.info(
            "screener.run_requested",
            extra={"user": str(request.user.id), "strategy": str(strategy.id), "run_id": str(run.id)},
        )
        return ok({"run_id": str(run.id)}, status=202)


# ---------------------------------------------------------------------------
# GET …/screen/runs/  and  GET …/screen/runs/{run_id}/
# ---------------------------------------------------------------------------
class ScreenRunListView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="screener_run_list", tags=["screener"])
    def get(self, request, strategy_id):
        if not _enabled():
            return _feature_disabled()
        strategy = _load_strategy(request, strategy_id)
        if strategy is None:
            return _not_found()
        try:
            limit = int(request.query_params.get("limit", RUNS_LIST_DEFAULT))
        except (TypeError, ValueError):
            limit = RUNS_LIST_DEFAULT
        limit = max(1, min(RUNS_LIST_MAX, limit))
        runs = ScreenRun.objects.filter(
            user=request.user, strategy=strategy,
        ).order_by("-created_at")[:limit]
        return ok([run_summary(r) for r in runs])


class ScreenRunDetailView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True

    @extend_schema(operation_id="screener_run_detail", tags=["screener"])
    def get(self, request, strategy_id, run_id):
        if not _enabled():
            return _feature_disabled()
        strategy = _load_strategy(request, strategy_id)
        if strategy is None:
            return _not_found()
        # Runs are strictly owner-scoped: another user's run id is a 404 here,
        # exactly like a non-existent one.
        run = ScreenRun.objects.filter(
            id=run_id, user=request.user, strategy=strategy,
        ).first()
        if run is None:
            return fail("SCREEN_RUN_NOT_FOUND", "Screen run not found.", status=404)
        return ok(run_detail(run))
