"""Feature pipeline (M06 §6.3).

Computes the breadth/stress/credit/macro feature vector from provided inputs
(prices, VIX, spreads, macro), then standardizes each feature via a rolling
z-score clipped to [-4, 4]. Pure + deterministic → reproducible (AC-06-10):
same inputs + same rolling history ⇒ identical vector ⇒ identical content hash.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from .hmm_model import FEATURE_ORDER

Z_CLIP = 4.0
ROLL_WINDOW = 252

# Stress/credit/macro inputs whose ABSENCE must neutralize (not fail toward
# risk-on). A fabricated raw 0 z-scores strongly negative against a history of
# real elevated values, and (their rule weights are negative) pins the score to
# RISK_ON — data loss must de-risk, not de-stress (FIX-M13).
CRITICAL_INPUTS = ("vix", "hy_oas", "move", "ig_oas")
_INPUT_TO_FEATURES = {
    "vix": ("vix", "vix_term_ratio"),
    "hy_oas": ("hy_oas",),
    "move": ("move",),
    "ig_oas": ("ig_oas",),
}


def missing_critical_inputs(inputs: dict) -> list[str]:
    """Critical stress/macro inputs that are absent or unusable (0/None)."""
    return [k for k in CRITICAL_INPUTS if inputs.get(k) in (None, "", 0, 0.0)]


def neutral_feature_keys(missing_inputs) -> set[str]:
    """Standardized-feature keys to force to 0 (neutral) for missing inputs."""
    keys: set[str] = set()
    for k in missing_inputs:
        keys.update(_INPUT_TO_FEATURES.get(k, ()))
    return keys


def _rsi(closes: pd.Series, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0).tail(period).mean()
    loss = (-delta.clip(upper=0)).tail(period).mean()
    if loss == 0:
        return 100.0
    rs = gain / loss
    return float(100 - (100 / (1 + rs)))


def _mom(closes: pd.Series, n: int) -> float:
    if len(closes) <= n:
        return 0.0
    prev = closes.iloc[-n - 1]
    return 0.0 if prev == 0 else float(closes.iloc[-1] / prev - 1.0)


def compute_raw_features(inputs: dict) -> dict:
    """Compute the raw (unstandardized) feature vector. Missing inputs → 0."""
    feats: dict[str, float] = {}
    spy = pd.Series([float(x) for x in inputs.get("spy_closes", [])], dtype=float)
    if len(spy) > 1:
        feats["mom_50"] = _mom(spy, 50)
        feats["mom_200"] = _mom(spy, 200)
        feats["rsi_14"] = _rsi(spy, 14)

    constituents = inputs.get("constituents", {})
    if constituents:
        above50 = above200 = adv = dec = nh = nl = total = 0
        for closes in constituents.values():
            c = pd.Series([float(x) for x in closes], dtype=float)
            if len(c) < 200:
                continue
            total += 1
            above50 += int(c.iloc[-1] > c.tail(50).mean())
            above200 += int(c.iloc[-1] > c.tail(200).mean())
            if c.iloc[-1] >= c.iloc[-2]:
                adv += 1
            else:
                dec += 1
            nh += int(c.iloc[-1] >= c.tail(ROLL_WINDOW).max())
            nl += int(c.iloc[-1] <= c.tail(ROLL_WINDOW).min())
        if total:
            feats["pct_above_50sma"] = above50 / total * 100.0
            feats["pct_above_200sma"] = above200 / total * 100.0
            feats["ad_ratio"] = adv / max(dec, 1)
            feats["nh_nl_diff"] = float(nh - nl)

    feats["mcclellan_osc"] = float(inputs.get("mcclellan_osc", 0.0) or 0.0)
    vix = float(inputs.get("vix", 0.0) or 0.0)
    feats["vix"] = vix
    feats["vix_term_ratio"] = vix / max(float(inputs.get("vix3m", 0.0) or 0.0), 0.01)
    feats["move"] = float(inputs.get("move", 0.0) or 0.0)
    feats["hy_oas"] = float(inputs.get("hy_oas", 0.0) or 0.0)
    feats["ig_oas"] = float(inputs.get("ig_oas", 0.0) or 0.0)
    feats["yield_spread"] = float(inputs.get("y10", 0.0) or 0.0) - float(inputs.get("y2", 0.0) or 0.0)
    feats["dxy"] = float(inputs.get("dxy", 0.0) or 0.0)
    return {k: float(feats.get(k, 0.0) or 0.0) for k in FEATURE_ORDER}


def standardize(raw: dict, history: dict, neutral_keys=()) -> dict:
    """Z-score each feature against its rolling raw history, clip to [-4, 4].

    ``neutral_keys`` (features whose source input was missing) are forced to 0
    instead of z-scoring a fabricated raw value — data loss neutralizes (FIX-M13).
    """
    neutral = set(neutral_keys)
    out = {}
    for k in FEATURE_ORDER:
        if k in neutral:
            out[k] = 0.0
            continue
        hist = [float(x) for x in history.get(k, [])][-ROLL_WINDOW:]
        if len(hist) >= 2:
            arr = np.array(hist, dtype=float)
            mu, sd = float(arr.mean()), float(arr.std())
            z = 0.0 if sd == 0 else (float(raw.get(k, 0.0)) - mu) / sd
        else:
            z = 0.0
        out[k] = float(max(-Z_CLIP, min(Z_CLIP, z)))
    return out


def content_hash(features: dict) -> str:
    payload = {k: round(float(features.get(k, 0.0)), 6) for k in FEATURE_ORDER}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
