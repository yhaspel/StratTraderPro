"""Screener pipeline task (M16 §6.4).

Runs on the DEFAULT queue — no route entry, no beat entry (the M09 lesson: a
route glob drags unrelated tasks onto a dedicated queue). Its own time limits
override the 30s/45s global default, because a 50-candidate derived screen
does ~1+limit vendor calls and would otherwise be SIGKILLed mid-loop.
"""
from __future__ import annotations

import logging
import time

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone

from apps.marketdata.fmp import (
    FMPCircuitOpen,
    FMPClient,
    FMPError,
    FMPRateLimited,
    FMPServerError,
)
from apps.marketdata.keys import resolve_key
from apps.marketdata.services import upsert_bars

from . import enrich
from .criteria import LIMIT_DEFAULT
from .metrics import SCREEN_RUN_DURATION_SECONDS, SCREEN_RUNS_TOTAL
from .models import HISTORY_KEEP, ScreenRun

logger = logging.getLogger(__name__)


def _empty_counts() -> dict:
    """Every count is always present, so the panel never has to guess whether a
    zero means "none" or "not measured" (AC-16-7: no silent truncation)."""
    return {
        "vendor_matches": 0,
        "enriched": 0,
        "returned": 0,
        "insufficient_history": 0,
        "skipped_rate_limited": 0,   # FMP 429 / breaker open — quota, retry later
        "skipped_unavailable": 0,    # A4: vendor outage, or a per-symbol 4xx
    }


@shared_task(bind=True, ignore_result=True, soft_time_limit=240, time_limit=300)
def run_screen(self, run_id):
    """Execute one screen. The task argument is ``run_id`` ONLY — never the key
    (§11 key-leak surfaces)."""
    try:
        run = ScreenRun.objects.select_related("user", "strategy").get(id=run_id)
    except ScreenRun.DoesNotExist:
        logger.warning("screener.run_missing", extra={"run_id": str(run_id)})
        return

    run.status = ScreenRun.Status.RUNNING
    run.started_at = timezone.now()
    run.celery_task_id = self.request.id or ""
    run.save(update_fields=["status", "started_at", "celery_task_id"])
    started = time.monotonic()
    logger.info("screener.run_started", extra={"run_id": str(run.id)})

    try:
        _execute(run)
    except _Failed as exc:
        _fail(run, exc.code, started)
    except SoftTimeLimitExceeded:
        _fail(run, "SCREEN_TIME_CAP", started)
    except Exception:  # noqa: BLE001 — any failure marks the run FAILED, never wedges
        logger.exception("screener.run_error", extra={"run_id": str(run.id)})
        _fail(run, "SCREEN_FAILED", started)
    else:
        _finish(run, started)
    finally:
        _prune_history(run)


def _execute(run: ScreenRun) -> None:
    counts = _empty_counts()
    # ``run.criteria`` is the snapshot the view stored: the same object the
    # criteria endpoint serves, so a run is self-describing (A7).
    snapshot = run.criteria or {}
    vendor_params = snapshot.get("fmp_params") or {}
    derived = snapshot.get("derived") or {}
    limit = int(snapshot.get("limit") or LIMIT_DEFAULT)

    # 1) The key can be REMOVED between enqueue and execution — re-resolve here
    #    rather than trusting the view's check (guardrail: never read
    #    settings.FMP_API_KEY directly).
    api_key = resolve_key("FMP")
    if not api_key:
        raise _Failed("FMP_NOT_CONFIGURED")

    client = FMPClient(api_key=api_key)
    try:
        # 2) Vendor stage — exactly ONE screener call per run (AC-16-5).
        try:
            vendor_rows = client.company_screener(vendor_params) or []
        except (FMPRateLimited, FMPCircuitOpen):
            raise _Failed("FMP_RATE_LIMITED") from None
        except FMPError:
            # Outage with a cold cache, or a 4xx (bad key / tier-gated
            # endpoint) — both land as an honest FAILED run (§6.4 step 2).
            raise _Failed("FMP_UNAVAILABLE") from None

        if not isinstance(vendor_rows, list):
            vendor_rows = []
        counts["vendor_matches"] = len(vendor_rows)
        candidates = vendor_rows[:limit]  # hard enrichment cap (AC-16-5)

        # 3) Derived stage — only when the block actually asks for one.
        if not derived:
            rows = [enrich.result_row(r, None) for r in candidates]
            counts["enriched"] = 0
        else:
            rows, degraded = _enrich_candidates(client, candidates, derived, counts)
            run.degraded = run.degraded or degraded
    finally:
        client.close()

    # 4) Rank deterministically, persist.
    ranked = enrich.rank(rows, derived)
    counts["returned"] = len(ranked)
    run.results = ranked
    run.counts = counts
    run.status = ScreenRun.Status.DONE


def _enrich_candidates(client, candidates, derived, counts):
    """Per-candidate daily-bar enrichment with the A4 degrade ladder.

    A4 splits what the spec lumped together:
      * ``FMPRateLimited`` / ``FMPCircuitOpen`` -> quota problem, STOP fetching;
        the raiser plus every unfetched candidate counts as
        ``skipped_rate_limited``.
      * ``FMPServerError``                      -> vendor outage with a cold
        cache, STOP fetching; raiser + remainder count as ``skipped_unavailable``.
      * bare ``FMPError`` (4xx, i.e. ONE bad/delisted ticker) -> skip just that
        symbol, count it in ``skipped_unavailable``, KEEP GOING.
    Any of the three sets ``degraded`` — the run finishes DONE and says so.
    """
    rows: list[dict] = []
    degraded = False
    min_history = derived.get("min_history", 0)

    for index, vendor_row in enumerate(candidates):
        symbol = (vendor_row.get("symbol") or "").upper()
        if not symbol:
            counts["skipped_unavailable"] += 1
            degraded = True
            continue
        try:
            bars = client.daily_bars(symbol)
        except (FMPRateLimited, FMPCircuitOpen):
            # Raiser + every candidate we never got to.
            counts["skipped_rate_limited"] += len(candidates) - index
            return rows, True
        except FMPServerError:
            counts["skipped_unavailable"] += len(candidates) - index
            return rows, True
        except FMPError:
            counts["skipped_unavailable"] += 1
            degraded = True
            continue

        if bars:
            # Free reuse for M06A — the bars we already paid for land in the
            # shared Bar store (§6.4 step 3).
            try:
                upsert_bars(symbol, "1d", bars)
            except Exception:  # noqa: BLE001 — a store hiccup must not fail the screen
                logger.warning("screener.upsert_failed", extra={"symbol": symbol})

        metrics = enrich.compute_metrics(bars)
        if metrics is None or metrics["n_bars"] < min_history:
            counts["insufficient_history"] += 1
            continue
        counts["enriched"] += 1
        if enrich.passes(metrics, derived):
            rows.append(enrich.result_row(vendor_row, metrics))

    return rows, degraded


class _Failed(Exception):
    """Internal signal carrying the run's terminal ``error_code``."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _finish(run: ScreenRun, started: float) -> None:
    run.finished_at = timezone.now()
    run.save()
    duration = time.monotonic() - started
    SCREEN_RUN_DURATION_SECONDS.observe(duration)
    SCREEN_RUNS_TOTAL.labels(result="degraded" if run.degraded else "done").inc()
    logger.info(
        "screener.run_finished",
        extra={
            "run_id": str(run.id),
            "degraded": run.degraded,
            "counts": run.counts,
            "duration_s": round(duration, 3),
        },
    )


def _fail(run: ScreenRun, code: str, started: float) -> None:
    run.status = ScreenRun.Status.FAILED
    run.error_code = code
    run.counts = run.counts or _empty_counts()
    run.finished_at = timezone.now()
    run.save()
    duration = time.monotonic() - started
    SCREEN_RUN_DURATION_SECONDS.observe(duration)
    SCREEN_RUNS_TOTAL.labels(result="failed").inc()
    logger.warning(
        "screener.run_failed",
        extra={"run_id": str(run.id), "error_code": code, "duration_s": round(duration, 3)},
    )


def _prune_history(run: ScreenRun) -> None:
    """Keep the newest ``HISTORY_KEEP`` runs per (user, strategy) — inline, no
    beat job (§6.3). Best-effort: retention must never fail a finished run."""
    try:
        stale = list(
            ScreenRun.objects.filter(user_id=run.user_id, strategy_id=run.strategy_id)
            .order_by("-created_at")
            .values_list("id", flat=True)[HISTORY_KEEP:]
        )
        if stale:
            ScreenRun.objects.filter(id__in=stale).delete()
    except Exception:  # noqa: BLE001 — pragma: no cover
        logger.warning("screener.prune_failed", extra={"run_id": str(run.id)})
