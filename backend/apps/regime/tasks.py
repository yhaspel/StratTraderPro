"""Regime Celery tasks (M06 §6.8) — nightly HMM retrain + feature compute."""
from __future__ import annotations

import logging

import numpy as np
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_MIN_TRAIN_ROWS = 120
_HOLDOUT = 90


@shared_task(bind=True, ignore_result=True)
def retrain_hmm(self):
    """AC-06-4: fit on ~10y of daily standardized features, validate on the last
    90 OOS, activate only if non-regressive vs the current model."""
    from .hmm_model import (
        features_to_matrix,
        label_states,
        serialize_model,
        train_hmm,
    )
    from .metrics import HMM_RETRAIN_TOTAL
    from .models import FeatureVectorSnapshot, HMMModel
    from .services import activate_model

    snaps = list(
        FeatureVectorSnapshot.objects.filter(scope="MARKET").order_by("ts").values_list("features", flat=True)
    )
    if len(snaps) < _MIN_TRAIN_ROWS:
        HMM_RETRAIN_TOTAL.labels(result="skipped_insufficient_data").inc()
        return {"skipped": "insufficient_data", "rows": len(snaps)}

    X = features_to_matrix(snaps)
    train_X, hold_X = X[:-_HOLDOUT], X[-_HOLDOUT:]
    try:
        model, train_ll = train_hmm(train_X, seed=getattr(settings, "REGIME_HMM_SEED", 42))
        holdout_ll = float(model.score(hold_X))
    except Exception:
        logger.exception("hmm.retrain.failed")
        HMM_RETRAIN_TOTAL.labels(result="fit_failed").inc()
        return {"error": "fit_failed"}

    # A degenerate fit can yield a non-finite LL without raising. Reject it —
    # activating a NaN-LL model would make every future swap comparison False
    # (NaN semantics) and lock out all subsequent retrains (M2).
    if not (np.isfinite(train_ll) and np.isfinite(holdout_ll)):
        HMM_RETRAIN_TOTAL.labels(result="non_finite_ll").inc()
        return {"error": "non_finite_ll"}

    labels = label_states(model)
    now = timezone.now()
    hm = HMMModel.objects.create(
        version=now.isoformat(),
        n_states=4,
        params=serialize_model(model, labels),
        state_labels={str(k): v for k, v in labels.items()},
        train_ll=train_ll,
        holdout_ll=holdout_ll,
        trained_at=now,
        active=False,
    )
    # Rescore the incumbent on THIS holdout window so the swap guard compares
    # like-for-like, not against a stored LL from a different window (FIX-M9).
    activated = activate_model(hm, hold_X=hold_X)
    return {"version": hm.version, "holdout_ll": holdout_ll, "activated": activated}


def _daily_source_configured() -> bool:
    """The daily pipeline is a genuine no-op only when the market-data keys are
    truly absent — checked here, not assumed (FIX-H10)."""
    return bool(getattr(settings, "FMP_API_KEY", "")) and bool(getattr(settings, "FRED_API_KEY", ""))


def gather_daily_inputs(fmp=None, fred=None) -> dict:
    """Fetch the day's SPY bars + macro/credit series via the marketdata clients
    and assemble the feature-inputs dict. Every fetch is defensive: a failed one
    leaves its input absent so :func:`features.missing_critical_inputs` can flag
    a degraded (not risk-on) observation (FIX-M13)."""
    from apps.marketdata.fmp import FMPClient
    from apps.marketdata.fred import FREDClient

    fmp = fmp or FMPClient()
    fred = fred or FREDClient()

    def _closes(symbol):
        try:
            bars = fmp.daily_bars(symbol)
            closes = [float(b["close"]) for b in bars]
            # FMP returns newest-first; features want oldest→newest.
            return list(reversed(closes))[-300:]
        except Exception:  # noqa: BLE001 — missing data must not crash the beat
            logger.warning("regime.daily.bars_failed", extra={"symbol": symbol})
            return []

    def _fred_last(series_id):
        try:
            rows = fred.series(series_id)
            return float(rows[-1]["value"]) if rows else None
        except Exception:  # noqa: BLE001
            logger.warning("regime.daily.fred_failed", extra={"series": series_id})
            return None

    return {
        "spy_closes": _closes("SPY"),
        "vix": _fred_last("VIXCLS"),
        "hy_oas": _fred_last("BAMLH0A0HYM2"),
        "ig_oas": _fred_last("BAMLC0A0CM"),
        "y10": _fred_last("DGS10"),
        "y2": _fred_last("DGS2"),
        "dxy": _fred_last("DTWEXBGS"),
    }


def _rolling_history(scope="MARKET") -> dict:
    """Raw-feature history for the rolling z-score, oldest→newest."""
    from .features import ROLL_WINDOW
    from .hmm_model import FEATURE_ORDER
    from .models import FeatureVectorSnapshot

    snaps = list(
        FeatureVectorSnapshot.objects.filter(scope=scope)
        .order_by("-ts")
        .values_list("raw_features", flat=True)[:ROLL_WINDOW]
    )
    history: dict[str, list] = {k: [] for k in FEATURE_ORDER}
    for raw in reversed(snaps):
        for k in FEATURE_ORDER:
            if k in (raw or {}):
                history[k].append(raw[k])
    return history


def run_daily_feature_pipeline(*, inputs=None, fmp=None, fred=None, ts=None, scope="MARKET") -> dict:
    """Compute + standardize the day's feature vector, persist a
    FeatureVectorSnapshot, and produce a RegimeObservation. ``inputs`` may be
    injected (fixture-testable, no live keys)."""
    from .features import (
        compute_raw_features,
        content_hash,
        missing_critical_inputs,
        neutral_feature_keys,
        standardize,
    )
    from .models import FeatureVectorSnapshot
    from .services import compute_observation

    if inputs is None:
        inputs = gather_daily_inputs(fmp=fmp, fred=fred)

    raw = compute_raw_features(inputs)
    missing = missing_critical_inputs(inputs)
    neutral = neutral_feature_keys(missing)
    std = standardize(raw, _rolling_history(scope), neutral_keys=neutral)
    ts = ts or timezone.now()

    # Persist raw WITHOUT the neutralized (missing-input) features, so a later
    # day's rolling z-score history isn't polluted by today's fabricated 0s —
    # which would re-introduce the FIX-M13 risk-on bias one day downstream.
    persisted_raw = {k: v for k, v in raw.items() if k not in neutral}
    snap = FeatureVectorSnapshot.objects.update_or_create(
        scope=scope, ts=ts,
        defaults={"features": std, "raw_features": persisted_raw, "content_hash": content_hash(std)},
    )[0]
    obs = compute_observation(ts=ts, std_features=std, scope=scope, data_degraded=bool(missing))
    return {"snapshot": snap.id, "observation": obs.id, "degraded": bool(missing), "missing": missing}


@shared_task(bind=True, ignore_result=True)
def compute_features_daily(self):
    """Authoritative daily feature-vector task (M06 §6.8 / FIX-H10). Fetches the
    day's bars/macro, standardizes, persists a FeatureVectorSnapshot, and calls
    compute_observation. A genuine no-op only when the market-data keys are
    absent (checked, not assumed) — so regime is not permanently NEUTRAL once
    keys are configured."""
    if not _daily_source_configured():
        return {"skipped": "no_market_data_source_configured"}
    return run_daily_feature_pipeline()
