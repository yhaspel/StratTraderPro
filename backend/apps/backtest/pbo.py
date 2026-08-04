"""Probability of Backtest Overfitting — CSCV (Bailey et al. 2015), M09 §6.5.

The input matrix ``M`` is ``T×N`` daily net returns from ONE dedicated
full-range sweep per symbol (never assembled from per-window train sweeps —
overlapping windows would break CSCV's disjoint-block premise).

CSCV: split ``M`` into ``S=16`` contiguous time-ordered blocks; for each of the
C(16, 8) = 12 870 train/test partitions, find the in-sample-best combo and its
out-of-sample relative rank; PBO = fraction of partitions where the IS-best
lands in the **bottom half** out-of-sample.

**Vectorised** via precomputed per-block per-combo statistics (block sums/sums-of-
squares), evaluating all 12 870 partitions as matrix ops — a naive per-partition
Python loop would alone blow the ≤ 60 s CI smoke (AC-09-10).
"""
from __future__ import annotations

import itertools

import numpy as np

S_BLOCKS = 16  # fixed even block count — C(16,8)=12870; larger S explodes
_MIN_COMBOS = 10  # N < 10 → PBO undefined (skip)


def probability_of_backtest_overfitting(matrix: np.ndarray, s: int = S_BLOCKS) -> float | None:
    """Return PBO ∈ [0, 1], or ``None`` for degenerate inputs (N < 10 or T < 2S).

    ``matrix`` is ``T×N`` (rows = trading days, cols = combos)."""
    m = np.asarray(matrix, dtype="float64")
    if m.ndim != 2:
        return None
    t, n = m.shape
    if n < _MIN_COMBOS or t < 2 * s:
        return None
    if s % 2 != 0:
        raise ValueError("CSCV requires an even block count S.")

    rows_per_block = t // s
    t_trunc = rows_per_block * s
    m = m[:t_trunc]

    # Per-block per-combo statistics (block-additive → partition sums are matmuls).
    blocks = m.reshape(s, rows_per_block, n)
    block_sum = blocks.sum(axis=1)            # (S, N)
    block_sumsq = (blocks ** 2).sum(axis=1)   # (S, N)
    total_sum = block_sum.sum(axis=0)          # (N,)
    total_sumsq = block_sumsq.sum(axis=0)      # (N,)

    # All C(S, S/2) train-block partitions as a boolean membership matrix P (P×S).
    train_sets = list(itertools.combinations(range(s), s // 2))
    p_mat = np.zeros((len(train_sets), s), dtype="float64")
    for i, combo in enumerate(train_sets):
        p_mat[i, list(combo)] = 1.0

    count_is = (s // 2) * rows_per_block
    count_oos = count_is

    # Some BLAS backends emit spurious FP warnings on matmul even for finite
    # inputs — suppress; the sums are exact block-additive partition statistics.
    with np.errstate(all="ignore"):
        sum_is = p_mat @ block_sum          # (P, N)
        sumsq_is = p_mat @ block_sumsq      # (P, N)
        sum_oos = total_sum[None, :] - sum_is
        sumsq_oos = total_sumsq[None, :] - sumsq_is

        sharpe_is = _sharpe(sum_is, sumsq_is, count_is)
        sharpe_oos = _sharpe(sum_oos, sumsq_oos, count_oos)

    best_is = np.argmax(sharpe_is, axis=1)                    # (P,) IS-best combo per partition
    rows = np.arange(sharpe_oos.shape[0])
    oos_of_best = sharpe_oos[rows, best_is]                   # (P,) its OOS sharpe

    # Relative OOS rank of the IS-best among all combos (0 = worst, 1 = best).
    below = (sharpe_oos < oos_of_best[:, None]).sum(axis=1)   # strictly-worse count
    rel_rank = below / (n - 1)
    overfit = rel_rank <= 0.5                                 # bottom-half OOS ⇒ overfit
    return float(overfit.mean())


def _sharpe(sum_x: np.ndarray, sum_x2: np.ndarray, count: int) -> np.ndarray:
    """Per-partition per-combo Sharpe from block-additive sums. Zero-variance
    combos → -inf so they rank last (never IS-best, always OOS-worst)."""
    mean = sum_x / count
    var = sum_x2 / count - mean ** 2
    var = np.clip(var, 0.0, None)
    std = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(std > 0, mean / std, -np.inf)
    return out
