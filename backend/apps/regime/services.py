"""Regime orchestration (M06 §6.5/§6.6) — features → rule → HMM → ensemble.

``compute_observation`` runs the pipeline for one standardized feature vector
and persists a ``RegimeObservation``. Model swap logic (``activate_model``)
implements the AC-06-4 guard (activate only if holdout LL ≥ prior, or within 1%).
"""
from __future__ import annotations

import time

import numpy as np
from django.conf import settings
from django.utils import timezone

from . import ensemble, rule_classifier
from .hmm_model import STATE_LABELS, deserialize_model, features_to_matrix
from .metrics import HMM_RETRAIN_TOTAL, REGIME_COMPUTE_LATENCY, REGIME_MODEL_AGE
from .models import HMMModel, RegimeObservation

MODEL_STALE_HOURS = 48


def get_active_model():
    return HMMModel.objects.filter(active=True).order_by("-trained_at").first()


def model_degraded(model) -> bool:
    if model is None:
        return True
    age = (timezone.now() - model.trained_at).total_seconds()
    REGIME_MODEL_AGE.set(age)
    return age > MODEL_STALE_HOURS * 3600


def compute_observation(*, ts, std_features: dict, history_matrix=None, scope="MARKET", data_degraded=False):
    """Run rule + HMM + ensemble on one standardized vector; persist + return.

    ``data_degraded`` (a critical stress/macro input was missing this cycle)
    marks the observation degraded so the UI flags it (FIX-M13)."""
    t0 = time.monotonic()
    rule = rule_classifier.classify(std_features)

    hmm_state = ""
    hmm_probs: dict = {}
    model = get_active_model()
    degraded = model_degraded(model)
    if model is not None and not degraded:
        try:
            m = deserialize_model(model.params)
            X = history_matrix if history_matrix is not None else features_to_matrix([std_features])
            probs = m.predict_proba(X)[-1]
            labels = model.state_labels or {str(i): STATE_LABELS[i] for i in range(len(probs))}
            state_idx = int(np.argmax(probs))
            hmm_state = labels.get(str(state_idx), STATE_LABELS[state_idx % 4])
            hmm_probs = {labels.get(str(i), STATE_LABELS[i % 4]): round(float(p), 4) for i, p in enumerate(probs)}
        except Exception:  # pragma: no cover — decode failure → rule-only
            hmm_state, hmm_probs, degraded = "", {}, True

    conf = max(hmm_probs.values()) if hmm_probs else None
    label = ensemble.decide(rule.bucket, hmm_state or None, conf)

    obs = RegimeObservation.objects.update_or_create(
        scope=scope, ts=ts,
        defaults={
            "label": label,
            "rule_bucket": rule.bucket,
            "rule_score": rule.score,
            "hmm_state": hmm_state,
            "hmm_probs": hmm_probs,
            "top_features": rule.top_features,
            "model_version": model.version if model else "",
            "model_degraded": degraded or data_degraded,
            "ensemble_version": ensemble.ENSEMBLE_VERSION,
        },
    )[0]
    REGIME_COMPUTE_LATENCY.observe(time.monotonic() - t0)
    return obs


def activate_model(new: HMMModel, hold_X=None) -> bool:
    """AC-06-4 swap: activate ``new`` only if its holdout LL is ≥ the current
    active model's (or within 1%). Returns whether it was activated.

    The incumbent's *stored* LL came from a different training-time holdout, so
    it is not comparable to the candidate's. When ``hold_X`` (the new holdout
    window) is provided, rescore the incumbent on it and compare like-for-like
    — otherwise the guard reacts to data drift, not model quality (FIX-M9)."""
    current = get_active_model()
    activate = True
    if current is not None and current.holdout_ll is not None and new.holdout_ll is not None:
        current_ll = current.holdout_ll
        if hold_X is not None and current.params:
            try:
                current_ll = float(deserialize_model(current.params).score(hold_X))
            except Exception:  # pragma: no cover — undecodable incumbent → use stored LL
                current_ll = current.holdout_ll
        if current_ll is not None and np.isfinite(current_ll):
            better = new.holdout_ll >= current_ll
            within_1pct = abs(new.holdout_ll - current_ll) <= 0.01 * abs(current_ll)
            activate = better or within_1pct
    if activate:
        HMMModel.objects.filter(active=True).exclude(pk=new.pk).update(active=False)
        new.active = True
        new.save(update_fields=["active"])
        HMM_RETRAIN_TOTAL.labels(result="activated").inc()
    else:
        HMM_RETRAIN_TOTAL.labels(result="rejected").inc()
    return activate


def regime_ui_enabled() -> bool:
    return getattr(settings, "ENABLE_REGIME_UI", True)
