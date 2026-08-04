"""Gaussian HMM regime model (M06 §6.5).

Trains a 4-state ``hmmlearn.GaussianHMM`` on the daily feature matrix with N
random restarts (deterministic given a seed), assigns state→label by ranking
each state's mean risk-on-ness, and serializes params to JSON so the active
model can be reloaded for online decode + Viterbi without a retrain.
"""
from __future__ import annotations

import numpy as np
from hmmlearn.hmm import GaussianHMM

# Canonical feature order — must match apps.regime.features.FEATURE_ORDER.
FEATURE_ORDER = [
    "pct_above_50sma", "pct_above_200sma", "ad_ratio", "nh_nl_diff", "mcclellan_osc",
    "vix", "vix_term_ratio", "move", "hy_oas", "ig_oas",
    "mom_50", "mom_200", "rsi_14", "yield_spread", "dxy",
]

STATE_LABELS = ["BULL", "CHOP", "BEAR", "CRISIS"]


def features_to_matrix(feature_dicts: list[dict]) -> np.ndarray:
    return np.array(
        [[float(fd.get(k, 0.0) or 0.0) for k in FEATURE_ORDER] for fd in feature_dicts],
        dtype=float,
    )


def train_hmm(X: np.ndarray, *, n_states: int = 4, n_restarts: int = 20, seed: int = 42):
    """Fit with ``n_restarts`` seeds, return (best_model, best_log_likelihood)."""
    best, best_ll = None, -np.inf
    for i in range(n_restarts):
        m = GaussianHMM(
            n_components=n_states, covariance_type="diag", n_iter=50,
            random_state=seed + i, tol=1e-3,
        )
        try:
            m.fit(X)
            ll = m.score(X)
        except Exception:  # noqa: S112 — degenerate restart; try the next seed  # pragma: no cover
            continue
        if ll > best_ll:
            best_ll, best = ll, m
    if best is None:  # pragma: no cover
        raise RuntimeError("HMM failed to converge on any restart")
    return best, float(best_ll)


def label_states(model: GaussianHMM) -> dict:
    """Rank states most→least risk-on and assign BULL/CHOP/BEAR/CRISIS."""
    means = model.means_  # (n_states, n_features) in z-space
    idx = {k: FEATURE_ORDER.index(k) for k in ("mom_50", "mom_200", "vix", "hy_oas")}
    risk_on = (
        means[:, idx["mom_50"]] + means[:, idx["mom_200"]]
        - means[:, idx["vix"]] - means[:, idx["hy_oas"]]
    )
    order = np.argsort(-risk_on)  # descending
    return {int(state): STATE_LABELS[rank] for rank, state in enumerate(order)}


def serialize_model(model: GaussianHMM, labels: dict) -> dict:
    return {
        "startprob": model.startprob_.tolist(),
        "transmat": model.transmat_.tolist(),
        "means": model.means_.tolist(),
        "covars_diag": [np.diag(c).tolist() for c in model.covars_],
        "n_states": int(model.n_components),
        "state_labels": {str(k): v for k, v in labels.items()},
    }


def deserialize_model(params: dict) -> GaussianHMM:
    m = GaussianHMM(n_components=int(params["n_states"]), covariance_type="diag")
    m.startprob_ = np.array(params["startprob"], dtype=float)
    m.transmat_ = np.array(params["transmat"], dtype=float)
    m.means_ = np.array(params["means"], dtype=float)
    m.covars_ = np.array(params["covars_diag"], dtype=float)
    return m


def decode_current(model: GaussianHMM, X: np.ndarray):
    """Return (state_idx, prob_vector) for the LAST row of X."""
    probs = model.predict_proba(X)
    last = probs[-1]
    return int(np.argmax(last)), last.tolist()


def viterbi_sequence(model: GaussianHMM, X: np.ndarray) -> list[int]:
    _ll, seq = model.decode(X, algorithm="viterbi")
    return [int(s) for s in seq]
