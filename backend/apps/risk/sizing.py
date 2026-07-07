"""Position sizing (M08 §6.2).

Pure Python, no I/O — deterministic given (inputs, profile) so it is property-
testable and reusable by the M09 backtester. Every call site persists a
``SizingDecision`` (done by the caller, not here). The Kelly damper (plan §6.2)
is deferred until the M09 ``TradeHistory`` exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

# Regime → risk-scale (CRISIS halts sizing entirely).
REGIME_SCALE = {"CRISIS": 0.0, "BEAR": 0.3, "CHOP": 0.6, "NEUTRAL": 0.6, "BULL": 1.0}
_LONG_SIDES = {"LONG", "BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}
_DEFAULT_STOP_FRAC = 0.02  # 2% of price when no ATR/stop info


@dataclass(frozen=True)
class SizingInputs:
    requested_qty: Decimal
    side: str
    symbol: str
    price: Decimal
    equity: Decimal
    regime_label: str = "NEUTRAL"
    sentiment_polarity: float = 0.0
    intraday_dd_pct: float = 0.0
    atr14: Decimal | None = None
    stop_distance: Decimal | None = None
    contract_multiplier: Decimal = Decimal("1")
    lot_size: Decimal = Decimal("1")


@dataclass(frozen=True)
class SizingResult:
    ok: bool
    qty: Decimal
    reason: str = ""
    meta: dict = field(default_factory=dict)

    @classmethod
    def reject(cls, reason: str, meta=None):
        return cls(False, Decimal("0"), reason, meta or {})

    @classmethod
    def accept(cls, qty: Decimal, meta=None):
        return cls(True, qty, "", meta or {})


def _round_to_lot(qty: float, lot: float) -> float:
    lot = lot or 1.0
    return math.floor(qty / lot) * lot


def compute_size(inp: SizingInputs, profile) -> SizingResult:
    label = (inp.regime_label or "NEUTRAL").upper()
    scale = REGIME_SCALE.get(label, 0.6)
    is_long = str(inp.side).upper() in _LONG_SIDES

    # Strict-mode side/regime mismatch (AC-08-6).
    if getattr(profile, "strict_mode", False) and label in ("BEAR", "CRISIS") and is_long:
        return SizingResult.reject("REGIME_SIDE_MISMATCH")
    # CRISIS → size 0 (AC-08-5).
    if label == "CRISIS" or scale <= 0:
        return SizingResult.reject("REGIME_CRISIS")

    risk_pct = float(profile.risk_per_trade_pct) * scale
    price = max(float(inp.price), 0.01)
    equity = float(inp.equity)

    atr_stop = float(profile.atr_factor) * float(inp.atr14 or 0)
    stop_dist = max(float(inp.stop_distance or 0), atr_stop)
    if stop_dist <= 0:
        stop_dist = price * _DEFAULT_STOP_FRAC

    dollar_risk = equity * (risk_pct / 100.0)
    raw_qty = dollar_risk / (stop_dist * float(inp.contract_multiplier or 1))

    # Position-size clamp.
    max_qty_by_pos = (equity * float(profile.max_position_pct) / 100.0) / price
    qty = min(raw_qty, max_qty_by_pos)

    # Sentiment adjustment.
    if inp.sentiment_polarity > 0.7 and is_long:
        qty *= 1.10
    elif inp.sentiment_polarity < -0.5 and is_long:
        qty *= 0.70

    # Soft-stop reduction (AC-08-12).
    soft_applied = inp.intraday_dd_pct >= float(profile.soft_stop_pct)
    if soft_applied:
        qty *= 0.5

    qty = _round_to_lot(qty, float(inp.lot_size or 1))
    meta = {
        "regime_label": label, "regime_scale": scale, "risk_pct": round(risk_pct, 4),
        "stop_dist": round(stop_dist, 4), "raw_qty": round(raw_qty, 6),
        "max_qty_by_pos": round(max_qty_by_pos, 6), "sentiment": inp.sentiment_polarity,
        "soft_stop_applied": soft_applied,
    }
    if qty <= 0:
        return SizingResult.reject("SIZING_ZERO", meta)
    return SizingResult.accept(Decimal(str(qty)), meta)
