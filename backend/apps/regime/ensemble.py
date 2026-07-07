"""Regime ensemble (M06 §6.6) — deterministic rule + HMM combination.

Given (rule_bucket, hmm_state, hmm_confidence) the label is fully determined by
the decision table + ENSEMBLE_VERSION (AC-06-6).
"""
from __future__ import annotations

ENSEMBLE_VERSION = "v1"

# rule bucket → fallback label when the HMM doesn't override.
_RULE_TO_LABEL = {
    "RISK_ON": "BULL",
    "NEUTRAL": "NEUTRAL",
    "RISK_OFF": "BEAR",
    "PANIC": "CRISIS",
}


def decide(rule_bucket: str, hmm_state: str | None, hmm_confidence: float | None) -> str:
    """Return the ensemble label. ``hmm_state`` in {BULL,CHOP,BEAR,CRISIS} or None
    (HMM degraded/unavailable → rule-only)."""
    conf = float(hmm_confidence or 0.0)

    if rule_bucket == "PANIC":
        return "CRISIS"

    if rule_bucket == "RISK_ON":
        if hmm_state == "BULL":
            return "BULL"
        if hmm_state == "CHOP":
            return "CHOP" if conf > 0.7 else "NEUTRAL"

    if rule_bucket == "RISK_OFF":
        if hmm_state in ("BEAR", "CHOP", "CRISIS"):
            return "BEAR"

    # "other" (NEUTRAL, or unmatched RISK_ON/RISK_OFF combos): strong HMM overrides.
    if hmm_state == "BULL" and conf > 0.8:
        return "BULL"
    if hmm_state in ("BEAR", "CRISIS") and conf > 0.8:
        return "BEAR"

    # Fallback → rule's own label.
    return _RULE_TO_LABEL.get(rule_bucket, "NEUTRAL")
