"""Rule-based breadth/stress classifier (M06 §6.4).

Weighted linear combination of standardized (z-scored) features → score in
[0,100] → bucket. Deterministic given (features, weights). Weights are signed by
risk-on direction and overridable via ``settings.REGIME_RULE_WEIGHTS``.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

# Signed weights: positive = risk-on when the z-score is high.
DEFAULT_WEIGHTS = {
    "pct_above_50sma": 1.5,
    "pct_above_200sma": 1.5,
    "ad_ratio": 1.0,
    "nh_nl_diff": 1.0,
    "mcclellan_osc": 0.8,
    "vix": -1.8,
    "vix_term_ratio": -1.0,
    "move": -1.0,
    "hy_oas": -1.8,
    "ig_oas": -1.2,
    "mom_50": 1.2,
    "mom_200": 1.2,
    "rsi_14": 0.5,
    "yield_spread": 0.6,
    "dxy": -0.5,
}

# Score → bucket thresholds (AC-06-3).
BUCKETS = [(70, "RISK_ON"), (50, "NEUTRAL"), (30, "RISK_OFF"), (0, "PANIC")]

_SCALE = 6.0  # maps a typical summed contribution into the [0,100] band


@dataclass(frozen=True)
class RuleResult:
    score: float
    bucket: str
    contributions: dict  # feature → signed contribution
    top_features: list  # [{"name", "z"}]


def _weights() -> dict:
    return {**DEFAULT_WEIGHTS, **getattr(settings, "REGIME_RULE_WEIGHTS", {})}


def classify(features: dict) -> RuleResult:
    weights = _weights()
    contributions = {}
    total = 0.0
    for name, w in weights.items():
        z = float(features.get(name, 0.0) or 0.0)
        c = w * z
        contributions[name] = c
        total += c
    score = 50.0 + _SCALE * total
    score = max(0.0, min(100.0, score))
    bucket = next(b for thr, b in BUCKETS if score >= thr)
    top = sorted(
        ({"name": n, "z": round(float(features.get(n, 0.0) or 0.0), 3)} for n in weights),
        key=lambda d: abs(d["z"]),
        reverse=True,
    )[:3]
    return RuleResult(
        score=round(score, 2), bucket=bucket, contributions=contributions, top_features=top
    )
