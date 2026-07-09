"""Backtest API (M09 §6.7). JWT + MFA per repo defaults; ``{"data": ...}`` /
``{"error": {...}}`` envelope; PageNumber pagination (25). Owner-scoped end to
end (§11)."""
from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.http import HttpResponse
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_portal.flags import is_enabled
from apps.strategies.models import Strategy
from apps.users.permissions import IsAuthenticatedAndMFAEnforced
from apps.users.responses import fail, ok

from .exceptions import DISABLED, GRID_TOO_LARGE, LIMIT_CONCURRENT, NO_ADAPTER, VALIDATION, BacktestError
from .models import BacktestRun
from .serializers import (
    MAX_WINDOWS,
    BacktestRunCreateSerializer,
    BacktestRunDetailSerializer,
    BacktestRunListSerializer,
)
from .strategies import get_adapter
from .vbt_engine import make_combos

_PAGE_SIZE = 25
_MAX_CONCURRENT = 2  # §11 per-user concurrency cap
_CODE_STATUS = {GRID_TOO_LARGE: 400, NO_ADAPTER: 400, VALIDATION: 400, LIMIT_CONCURRENT: 409}


def _disabled_response():
    if not is_enabled("BACKTEST_ENABLED"):
        return fail(DISABLED, "Backtesting is disabled.", status=503)
    return None


class _BaseBacktestView(APIView):
    permission_classes = [IsAuthenticatedAndMFAEnforced]
    mfa_required = True


def _visible_strategies(user):
    """System strategies (backtestable by anyone) + the caller's own (§11)."""
    return Strategy.objects.filter(Q(is_system=True) | Q(owner=user), is_enabled=True)


class BacktestStrategyListView(_BaseBacktestView):
    """Picker source: backtestable strategies + whether an adapter is registered."""

    @extend_schema(operation_id="backtest_strategies", tags=["backtest"])
    def get(self, request):
        disabled = _disabled_response()
        if disabled:
            return disabled
        rows = [
            {"id": str(s.id), "slug": s.slug, "name": s.name, "is_system": s.is_system,
             "has_adapter": get_adapter(s.slug) is not None}
            for s in _visible_strategies(request.user).order_by("-is_system", "name")
        ]
        return ok(rows)


class BacktestRunListCreateView(_BaseBacktestView):
    @extend_schema(operation_id="backtest_runs_list", tags=["backtest"])
    def get(self, request):
        disabled = _disabled_response()
        if disabled:
            return disabled
        qs = BacktestRun.objects.filter(user=request.user).select_related("strategy").order_by("-created_at")
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"].upper())
        if p.get("from") and parse_datetime(p["from"]):
            qs = qs.filter(created_at__gte=parse_datetime(p["from"]))
        if p.get("to") and parse_datetime(p["to"]):
            qs = qs.filter(created_at__lte=parse_datetime(p["to"]))
        total = qs.count()
        try:
            page = max(1, int(p.get("page", 1)))
        except (TypeError, ValueError):
            page = 1
        start = (page - 1) * _PAGE_SIZE
        rows = list(qs[start:start + _PAGE_SIZE])
        num_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        return Response({
            "data": BacktestRunListSerializer(rows, many=True).data,
            "meta": {"page": page, "page_size": _PAGE_SIZE, "total": total, "num_pages": num_pages},
        })

    @extend_schema(operation_id="backtest_runs_create", request=BacktestRunCreateSerializer, tags=["backtest"])
    def post(self, request):
        disabled = _disabled_response()
        if disabled:
            return disabled
        ser = BacktestRunCreateSerializer(data=request.data)
        if not ser.is_valid():
            return fail(VALIDATION, "Invalid backtest configuration.", status=400, details=ser.errors)
        data = ser.validated_data

        # Concurrency cap (§11).
        active = BacktestRun.objects.filter(
            user=request.user,
            status__in=(BacktestRun.Status.QUEUED, BacktestRun.Status.RUNNING, BacktestRun.Status.CANCELLING),
        ).count()
        if active >= _MAX_CONCURRENT:
            return fail(LIMIT_CONCURRENT, f"At most {_MAX_CONCURRENT} concurrent runs.", status=409)

        strategy = _visible_strategies(request.user).filter(id=data["strategy"]).first()
        if strategy is None:
            return fail(VALIDATION, "Unknown strategy or not accessible.", status=400)
        adapter = get_adapter(strategy.slug)
        if adapter is None:
            return fail(NO_ADAPTER, "No Python adapter registered for this strategy.", status=400)

        try:
            grid = _effective_grid(adapter, data["param_grid"])
            make_combos(grid)  # enforces the ≤ 500-combo cap
            self._check_windows(data)
        except BacktestError as e:
            return fail(e.code, e.message, status=_CODE_STATUS.get(e.code, 400), details=e.details or None)

        config = _build_config(strategy, data, grid)
        run = BacktestRun.objects.create(
            user=request.user, strategy=strategy, config=config,
            retention_days=data["retention_days"], status=BacktestRun.Status.QUEUED,
        )
        from .tasks import run_backtest

        run_backtest.delay(str(run.id))
        return ok(BacktestRunDetailSerializer(run).data, status=201)

    @staticmethod
    def _check_windows(data) -> None:
        from .wf import WFConfig, compute_windows

        wf = WFConfig(
            start=data["start"], end=data["end"],
            train_days=data["train_window_days"], test_days=data["test_window_days"],
            step_days=data["step_days"], anchored=data["mode"] == "anchored",
        )
        n = len(compute_windows(wf))
        if n < 2:
            raise BacktestError(VALIDATION, "Configuration yields fewer than 2 complete windows.")
        if n > MAX_WINDOWS:
            raise BacktestError(VALIDATION, f"Configuration yields {n} windows (> {MAX_WINDOWS} cap).")


class BacktestRunDetailView(_BaseBacktestView):
    @extend_schema(operation_id="backtest_runs_detail", tags=["backtest"])
    def get(self, request, pk):
        disabled = _disabled_response()
        if disabled:
            return disabled
        run = _get_run(request.user, pk)
        if run is None:
            return fail("BACKTEST_RUN_NOT_FOUND", "Run not found.", status=404)
        return ok(BacktestRunDetailSerializer(run).data)


class BacktestRunCancelView(_BaseBacktestView):
    @extend_schema(operation_id="backtest_runs_cancel", tags=["backtest"])
    def post(self, request, pk):
        disabled = _disabled_response()
        if disabled:
            return disabled
        run = _get_run(request.user, pk)
        if run is None:
            return fail("BACKTEST_RUN_NOT_FOUND", "Run not found.", status=404)
        if run.status in BacktestRun.TERMINAL_STATUSES:
            return fail("BACKTEST_NOT_ACTIVE", "Run already finished.", status=409)
        run.status = BacktestRun.Status.CANCELLING
        run.save(update_fields=["status", "updated_at"])
        return ok({"id": str(run.id), "status": run.status}, status=202)


class _ReportDownloadView(_BaseBacktestView):
    fmt = "json"

    def get(self, request, pk):
        disabled = _disabled_response()
        if disabled:
            return disabled
        run = _get_run(request.user, pk)
        if run is None:
            return fail("BACKTEST_RUN_NOT_FOUND", "Run not found.", status=404)
        report = getattr(run, "report", None)
        if report is None:
            return fail("BACKTEST_REPORT_NOT_READY", "Report not available yet.", status=404)
        payload = {"json": report.json, "html": report.html, "pdf": report.pdf}[self.fmt]
        if payload is None:
            return fail("BACKTEST_ARTIFACT_EVICTED", "Artifact evicted by retention policy.", status=410)
        return self._respond(run, payload)

    def _respond(self, run, payload):
        import json as _json

        if self.fmt == "json":
            resp = HttpResponse(_json.dumps(payload).encode("utf-8"), content_type="application/json")
            resp["Content-Disposition"] = f'attachment; filename="backtest-{run.id}.json"'
        elif self.fmt == "html":
            resp = HttpResponse(bytes(payload), content_type="text/html; charset=utf-8")
            resp["Content-Disposition"] = f'inline; filename="backtest-{run.id}.html"'
        else:
            resp = HttpResponse(bytes(payload), content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="backtest-{run.id}.pdf"'
        return resp


class BacktestReportJsonView(_ReportDownloadView):
    fmt = "json"

    @extend_schema(operation_id="backtest_report_json", tags=["backtest"])
    def get(self, request, pk):
        return super().get(request, pk)


class BacktestReportHtmlView(_ReportDownloadView):
    fmt = "html"

    @extend_schema(operation_id="backtest_report_html", tags=["backtest"])
    def get(self, request, pk):
        return super().get(request, pk)


class BacktestReportPdfView(_ReportDownloadView):
    fmt = "pdf"

    @extend_schema(operation_id="backtest_report_pdf", tags=["backtest"])
    def get(self, request, pk):
        return super().get(request, pk)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _get_run(user, pk):
    return (
        BacktestRun.objects.filter(user=user, pk=pk)
        .select_related("strategy")
        .prefetch_related("segments")
        .first()
    )


def _effective_grid(adapter, user_grid: dict) -> dict:
    """User grid must be a subset refinement of the adapter's declared grid; an
    empty user grid ⇒ the full adapter grid (§6.2)."""
    declared = adapter.param_grid()
    if not user_grid:
        return declared
    effective = {}
    for key, values in user_grid.items():
        if key not in declared:
            raise BacktestError(VALIDATION, f"param_grid key '{key}' is not part of this adapter's grid.")
        allowed = set(declared[key])
        bad = [v for v in values if v not in allowed]
        if bad:
            raise BacktestError(VALIDATION, f"param_grid['{key}'] values not allowed: {bad}.")
        effective[key] = list(values)
    # Fill any adapter keys the user omitted with the adapter's full range.
    for key, values in declared.items():
        effective.setdefault(key, list(values))
    return effective


def _build_config(strategy, data, grid) -> dict:
    return {
        "strategy_id": str(strategy.id),
        "strategy_slug": strategy.slug,
        "symbols": data["symbols"],
        "start": data["start"].isoformat() if isinstance(data["start"], date) else str(data["start"]),
        "end": data["end"].isoformat() if isinstance(data["end"], date) else str(data["end"]),
        "tf": data["tf"],
        "train_window_days": data["train_window_days"],
        "test_window_days": data["test_window_days"],
        "step_days": data["step_days"],
        "mode": data["mode"],
        "metric": data["metric"],
        "initial_cash": data["initial_cash"],
        "param_grid": grid,
        "costs": dict(data["costs"]),
        "sizing_mode": data["sizing_mode"],
        "retention_days": data["retention_days"],
    }
