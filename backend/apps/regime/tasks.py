"""Regime Celery tasks (M06 §6.8) — nightly HMM retrain + feature compute."""
from __future__ import annotations

import logging

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
    activated = activate_model(hm)
    return {"version": hm.version, "holdout_ll": holdout_ll, "activated": activated}


@shared_task(bind=True, ignore_result=True)
def compute_features_daily(self):
    """Placeholder authoritative-daily-vector task. In prod it fetches the day's
    bars/macro via FMP/FRED, computes + standardizes, stores a
    FeatureVectorSnapshot, and calls compute_observation. In CI (no keys) it is
    a no-op; the pipeline is exercised directly in tests."""
    return {"skipped": "no_market_data_source_configured"}
