"""Backtest Celery orchestration (M09 §6.8).

``run_backtest`` is routed to the dedicated ``backtest`` queue via an **explicit
per-task route** in settings (NOT a glob — a glob would drag the eviction task
onto the backtest queue and silently break retention). ``evict_expired_artifacts``
stays on the default ``celery`` queue so retention keeps working even when the
backtest worker is scaled to zero / not yet provisioned.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

from . import events, stats
from .exceptions import DISABLED, TIME_CAP, BacktestError
from .metrics import (
    BACKTEST_ACTIVE_RUNS,
    BACKTEST_ARTIFACT_BYTES,
    BACKTEST_FAILED,
    BACKTEST_QUEUE_WAIT,
    BACKTEST_RUN_DURATION,
    BACKTEST_RUNS,
)
from .models import BacktestReport, BacktestRun, BacktestSegment

logger = logging.getLogger(__name__)

MAX_ARTIFACT_BYTES = 25 * 1024 * 1024  # §6.6 guard
_PROGRESS_MIN_INTERVAL = 1.0  # throttle progress pushes ≥ 1 s apart (§6.8)


class _Cancelled(Exception):
    pass


class _Progress:
    """Throttled progress emitter (≥ 1 s between WS pushes; DB stage/pct kept fresh)."""

    def __init__(self, run: BacktestRun, total_windows: int):
        self.run = run
        self.total = max(1, total_windows)
        self.done = 0
        self.start = time.monotonic()
        self._last_push = 0.0

    def update(self, stage: str, *, window_inc: int = 0, pct: int | None = None, force: bool = False) -> None:
        self.done += window_inc
        if pct is None:
            pct = int(90 * self.done / self.total)
        eta = self._eta()
        self.run.stage = stage
        self.run.pct = pct
        self.run.save(update_fields=["stage", "pct", "updated_at"])
        now = time.monotonic()
        if force or (now - self._last_push) >= _PROGRESS_MIN_INTERVAL:
            events.push_progress(self.run.user_id, self.run.id, pct, stage, eta)
            self._last_push = now

    def _eta(self) -> float | None:
        if self.done <= 0:
            return None
        elapsed = time.monotonic() - self.start
        per = elapsed / self.done
        return max(0.0, per * (self.total - self.done))


@shared_task(bind=True, ignore_result=True, soft_time_limit=1500, time_limit=1800)
def run_backtest(self, run_id):
    """Execute a walk-forward run. Soft/hard limits 25/30 min (AC-09-2)."""
    try:
        run = BacktestRun.objects.select_related("user", "strategy").get(id=run_id)
    except BacktestRun.DoesNotExist:
        logger.warning("backtest.run_missing", extra={"run_id": str(run_id)})
        return

    if not getattr(settings, "BACKTEST_ENABLED", True):
        _fail(run, DISABLED, "Backtesting is disabled.")
        return

    # Cancelled while still QUEUED (before the worker picked it up) → honor it and
    # never start executing (AC-09-9).
    if run.status == BacktestRun.Status.CANCELLING:
        _terminal(run, BacktestRun.Status.CANCELLED, events.CANCELLED)
        return

    # Queue-wait metric (enqueue → start).
    if run.created_at:
        BACKTEST_QUEUE_WAIT.observe(max(0.0, (timezone.now() - run.created_at).total_seconds()))

    run.status = BacktestRun.Status.RUNNING
    run.started_at = timezone.now()
    run.celery_task_id = self.request.id or ""
    run.stage = BacktestRun.Stage.LOADING
    run.save(update_fields=["status", "started_at", "celery_task_id", "stage", "updated_at"])
    BACKTEST_ACTIVE_RUNS.inc()

    try:
        _execute(run)
    except _Cancelled:
        _terminal(run, BacktestRun.Status.CANCELLED, events.CANCELLED)
    except SoftTimeLimitExceeded:
        _fail(run, TIME_CAP, "Run exceeded the 25-minute soft time limit.")
    except BacktestError as e:
        _fail(run, e.code, e.message)
    except Exception as e:  # noqa: BLE001 — any failure marks the run FAILED, never wedges
        logger.exception("backtest.run_failed", extra={"run_id": str(run.id)})
        _fail(run, "BACKTEST_ERROR", str(e)[:400])
    finally:
        BACKTEST_ACTIVE_RUNS.dec()


def _execute(run: BacktestRun) -> None:
    from .data import load_bars
    from .report import SymbolPayload, build_html, build_json, build_pdf, metrics_hash
    from .strategies import get_adapter
    from .vbt_engine import VectorbtSweepEngine
    from .wf import WFConfig, walk_forward

    cfg = run.config
    adapter = get_adapter(run.strategy.slug)
    if adapter is None:
        raise BacktestError("BACKTEST_NO_ADAPTER", f"No adapter for strategy {run.strategy.slug!r}.")

    symbols = [s.upper() for s in cfg["symbols"]]
    start = date.fromisoformat(cfg["start"])
    end = date.fromisoformat(cfg["end"])
    tf = cfg.get("tf", "1d")
    wf_cfg = WFConfig(
        start=start, end=end,
        train_days=int(cfg["train_window_days"]),
        test_days=int(cfg["test_window_days"]),
        step_days=int(cfg["step_days"]),
        anchored=cfg.get("mode") == "anchored",
    )
    grid = cfg["param_grid"]
    metric = cfg.get("metric", "sharpe")
    initial_cash = float(cfg.get("initial_cash", 100_000))
    costs = dict(cfg.get("costs", {}))
    costs["initial_cash"] = initial_cash
    replay_cfg = _replay_config(cfg, initial_cash)
    profile = _resolve_profile(run, cfg.get("sizing_mode"))

    from .wf import compute_windows
    windows_per_symbol = len(compute_windows(wf_cfg))
    prog = _Progress(run, total_windows=len(symbols) * windows_per_symbol)
    engine = VectorbtSweepEngine()

    def should_cancel() -> bool:
        status = BacktestRun.objects.filter(id=run.id).values_list("status", flat=True).first()
        return status == BacktestRun.Status.CANCELLING

    def on_window(done_in_symbol, total_in_symbol):
        prog.update(BacktestRun.Stage.SWEEPING, window_inc=1)

    payloads: list[SymbolPayload] = []
    for symbol in symbols:
        if should_cancel():
            raise _Cancelled()
        prog.update(BacktestRun.Stage.LOADING, force=True)
        bars = load_bars(symbol, tf, start, end, warmup_bars=adapter.warmup_bars)

        result = walk_forward(
            adapter=adapter, bars=bars, symbol=symbol, cfg=wf_cfg,
            sweep_engine=engine, replay_cfg=replay_cfg, metric=metric,
            grid=grid, costs=costs, profile=profile,
            should_cancel=should_cancel, on_window=on_window,
        )
        if should_cancel():
            raise _Cancelled()

        # PBO from ONE dedicated full-range sweep per symbol (§6.5).
        prog.update(BacktestRun.Stage.REPLAYING, force=True)
        from .pbo import probability_of_backtest_overfitting
        _, matrix = engine.returns_matrix(bars, start, end, adapter, grid, costs)
        pbo = probability_of_backtest_overfitting(matrix)

        all_trades = [t for wr in result.windows for t in wr.replay.trades]
        exposure_bars = sum(wr.replay.exposure_bars for wr in result.windows)
        n_bars = sum(wr.replay.n_bars for wr in result.windows)
        metrics = stats.compute_metrics(result.oos_equity, all_trades, initial_cash, exposure_bars, n_bars)
        stability = stats.sharpe_stability([wr.oos_metrics.get("sharpe", 0.0) for wr in result.windows])

        window_rows = _persist_segments(run, result)
        payloads.append(SymbolPayload(
            symbol=symbol, metrics=metrics, pbo=pbo, sharpe_stability=stability,
            windows=window_rows, equity=result.oos_equity, trades=all_trades,
        ))

    # -- reporting --------------------------------------------------------
    prog.update(BacktestRun.Stage.REPORTING, pct=95, force=True)
    json_dict = build_json(_report_config(run, cfg), payloads)
    mhash = metrics_hash(json_dict)
    html_bytes = build_html(_report_config(run, cfg), payloads)
    pdf_bytes = build_pdf(_report_config(run, cfg), payloads)
    _guard_size(html_bytes, pdf_bytes, json_dict)

    import json as _json
    json_bytes = len(_json.dumps(json_dict).encode("utf-8"))
    BacktestReport.objects.update_or_create(
        run=run,
        defaults={
            "json": json_dict, "html": html_bytes, "pdf": pdf_bytes,
            "html_bytes": len(html_bytes), "pdf_bytes": len(pdf_bytes), "json_bytes": json_bytes,
        },
    )
    run.summary = {"symbols": {p.symbol: {**p.metrics, "pbo": p.pbo} for p in payloads}}
    run.metrics_hash = mhash
    _refresh_artifact_gauge()
    _terminal(run, BacktestRun.Status.COMPLETED, events.COMPLETED, extra={"metrics_hash": mhash})


def _replay_config(cfg: dict, initial_cash: float):
    from .replay_engine import ReplayConfig

    costs = cfg.get("costs", {})
    return ReplayConfig(
        initial_cash=initial_cash,
        slippage_bps=float(costs.get("slippage_bps", 5.0)),
        per_order_usd=float(costs.get("per_order_usd", 0.0)),
        per_share_usd=float(costs.get("per_share_usd", 0.0)),
        volume_participation_pct=float(costs.get("volume_participation_pct", 10.0)),
        sizing_mode=cfg.get("sizing_mode", "fixed_qty_1"),
    )


def _resolve_profile(run: BacktestRun, sizing_mode):
    if sizing_mode != "production":
        return None
    from apps.risk.models import RiskProfile

    profile, _ = RiskProfile.objects.get_or_create(user=run.user)
    return profile


def _persist_segments(run: BacktestRun, result) -> list[dict]:
    rows = []
    for wr in result.windows:
        w = wr.window
        BacktestSegment.objects.update_or_create(
            run=run, symbol=result.symbol, window_index=w.index,
            defaults={
                "train_start": w.train_start, "train_end": w.train_end,
                "test_start": w.test_start, "test_end": w.test_end,
                "best_params": wr.best_params, "oos_metrics": wr.oos_metrics,
            },
        )
        rows.append({
            "window_index": w.index,
            "train_start": w.train_start.isoformat(), "train_end": w.train_end.isoformat(),
            "test_start": w.test_start.isoformat(), "test_end": w.test_end.isoformat(),
            "best_params": wr.best_params, "oos_metrics": wr.oos_metrics,
        })
    return rows


def _report_config(run: BacktestRun, cfg: dict) -> dict:
    return {**cfg, "strategy_slug": run.strategy.slug}


def _guard_size(html_bytes, pdf_bytes, json_dict) -> None:
    import json as _json

    for size in (len(html_bytes), len(pdf_bytes), len(_json.dumps(json_dict).encode("utf-8"))):
        if size > MAX_ARTIFACT_BYTES:
            raise BacktestError("BACKTEST_REPORT_TOO_LARGE", f"Artifact {size}B exceeds {MAX_ARTIFACT_BYTES}B.")


def _terminal(run: BacktestRun, status, event_type, *, extra=None) -> None:
    run.status = status
    run.stage = BacktestRun.Stage.REPORTING if status == BacktestRun.Status.COMPLETED else run.stage
    run.pct = 100 if status == BacktestRun.Status.COMPLETED else run.pct
    run.finished_at = timezone.now()
    run.save()
    BACKTEST_RUNS.labels(status=status).inc()
    if run.started_at and run.finished_at:
        BACKTEST_RUN_DURATION.observe((run.finished_at - run.started_at).total_seconds())
    events.push_terminal(run.user_id, run.id, event_type, extra)


def _fail(run: BacktestRun, code: str, message: str) -> None:
    run.status = BacktestRun.Status.FAILED
    run.error_code = code
    run.error_message = (message or code)[:500]
    run.finished_at = timezone.now()
    run.save()
    BACKTEST_RUNS.labels(status=BacktestRun.Status.FAILED).inc()
    BACKTEST_FAILED.labels(reason=code).inc()
    events.push_terminal(run.user_id, run.id, events.FAILED, {"error_code": code, "error_message": run.error_message})


def _refresh_artifact_gauge() -> None:
    from django.db.models import Sum

    agg = BacktestReport.objects.aggregate(
        j=Sum("json_bytes"), h=Sum("html_bytes"), p=Sum("pdf_bytes")
    )
    total = (agg["j"] or 0) + (agg["h"] or 0) + (agg["p"] or 0)
    BACKTEST_ARTIFACT_BYTES.set(float(total))


@shared_task(bind=True, ignore_result=True)
def evict_expired_artifacts(self):
    """Nightly (03:30 UTC, default ``celery`` queue): null artifacts on runs past
    retention; keep rows + ``run.summary`` + segments (AC-09-11)."""
    if not getattr(settings, "BACKTEST_ENABLED", True):
        # Eviction still runs while disabled — doubles as orphan cleanup (§15).
        pass
    now = timezone.now()
    evicted = 0
    reports = BacktestReport.objects.select_related("run").filter(evicted_at__isnull=True)
    for report in reports.iterator():
        run = report.run
        cutoff = run.created_at + timedelta(days=run.retention_days)
        if now >= cutoff:
            report.evict()
            evicted += 1
    _refresh_artifact_gauge()
    return {"evicted": evicted}
