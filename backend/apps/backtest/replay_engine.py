"""Custom in-repo replay engine (M09 §6.3, ADR-091).

Replaces backtrader (dropped: GPLv3 + dormant). A deliberately small event loop
with exactly-specified, path-dependent semantics. **Pure** — a function of its
inputs, no I/O, no RNG (the ``RiskProfile`` used for production sizing is passed
in by the caller, so the engine itself touches no DB).

Fill semantics (fixed, all four in ADR-091):

- Signals evaluated on bar close ``t`` → market entry filled at bar ``t+1`` open,
  adjusted by slippage bps (buy: ``open*(1+bps/1e4)``; sell mirrored).
- Stops/targets (``stop_pct``/``target_pct``) evaluated intra-bar on ``t+1…``:
  hit if ``low ≤ stop`` (long) / ``high ≥ target``; fill at the level, or at the
  open on a gap-through. **Same-bar both-hit → stop first** (conservative).
- Partial fills: qty capped at ``volume_participation_pct`` (default 10%) of the
  bar's volume; remainder re-attempted next bar (max 5 bars, then the rest is
  cancelled and logged on the trade record).
- Commissions: ``per_order_usd`` (default 0) + ``per_share_usd`` (default 0).
- Long-only in MVP; same-bar entries&exits both true → no-op; each test segment
  replays from ``initial_cash`` (OOS concatenation compounds in return space,
  §6.4); open positions at the segment's final bar are **force-closed at that
  bar's close** with slippage + commission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pandas as pd

from apps.risk.sizing import SizingInputs, compute_size

_MAX_FILL_BARS = 5  # partial fills re-attempted for at most this many bars


# ---------------------------------------------------------------------------
# ATR-14 — must replicate apps.risk.integration._atr14 EXACTLY (AC-09-12)
# ---------------------------------------------------------------------------
def atr14_from_bars(bars: pd.DataFrame, end_pos: int) -> Decimal | None:
    """Simple mean of the last ≤ 14 true ranges over the last 15 bars ending at
    ``end_pos`` (inclusive) — **not** Wilder smoothing.

    Mirrors ``apps.risk.integration._atr14`` (which reads the latest 15 stored
    bars). Uses ``Decimal(str(...))`` so the value is bit-identical to the
    Decimal path in production sizing when bar prices are exact decimals — the
    parity test (§10.1) pins the compared trade to the final bar so both sides
    see the same 15 bars.
    """
    lo = max(0, end_pos - 14)
    window = bars.iloc[lo : end_pos + 1]
    if len(window) < 2:
        return None
    highs = [Decimal(str(v)) for v in window["high"].tolist()]
    lows = [Decimal(str(v)) for v in window["low"].tolist()]
    closes = [Decimal(str(v)) for v in window["close"].tolist()]
    trs: list[Decimal] = []
    for i in range(1, len(window)):
        prev_c = closes[i - 1]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev_c), abs(lows[i] - prev_c))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def build_sizing_inputs(
    *,
    symbol: str,
    price: Decimal,
    equity: Decimal,
    atr14: Decimal | None,
    stop_distance: Decimal | None,
    side: str = "BUY",
) -> SizingInputs:
    """Construct the ``SizingInputs`` the replay feeds to ``compute_size`` in
    production-sizing mode. Regime/sentiment/intraday-dd are neutralised (the
    backtest has no live regime/sentiment feed); ``requested_qty`` is required by
    the dataclass but unread by ``compute_size`` (a §10.1 test asserts it stays
    unread). Divergence from live ``apply_sizing``: ``stop_distance`` is populated
    from the adapter's stops here, whereas production passes ``None`` (ADR-091)."""
    return SizingInputs(
        requested_qty=Decimal("0"),
        side=side,
        symbol=symbol,
        price=price,
        equity=equity,
        regime_label="NEUTRAL",
        sentiment_polarity=0.0,
        intraday_dd_pct=0.0,
        atr14=atr14,
        stop_distance=stop_distance,
        contract_multiplier=Decimal("1"),
        lot_size=Decimal("1"),
    )


# ---------------------------------------------------------------------------
# Config + result dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReplayConfig:
    initial_cash: float = 100_000.0
    slippage_bps: float = 5.0
    per_order_usd: float = 0.0
    per_share_usd: float = 0.0
    volume_participation_pct: float = 10.0  # % of bar volume
    sizing_mode: str = "fixed_qty_1"  # "production" | "fixed_qty_1"


@dataclass
class Trade:
    symbol: str
    entry_ts: pd.Timestamp
    exit_ts: pd.Timestamp
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    mfe: float  # max favorable excursion (best high − avg entry, per share)
    mae: float  # max adverse excursion (worst low − avg entry, per share)
    bars_held: int
    exit_reason: str  # signal | stop | target | force_close
    entry_commission: float = 0.0
    exit_commission: float = 0.0
    partial: bool = False
    cancelled_qty: float = 0.0


@dataclass
class ReplayResult:
    symbol: str
    equity: pd.Series  # per-bar mark-to-market equity over the test window
    trades: list[Trade] = field(default_factory=list)
    exposure_bars: int = 0
    n_bars: int = 0


# ---------------------------------------------------------------------------
# Internal position bookkeeping
# ---------------------------------------------------------------------------
@dataclass
class _Position:
    target_qty: float
    stop_pct: float | None
    target_pct: float | None
    qty: float = 0.0
    cost: float = 0.0  # Σ fill_qty × fill_price (cash spent on shares)
    bars_filling: int = 0
    complete: bool = False
    entry_ts: pd.Timestamp | None = None
    entry_bar: int = 0
    entry_commission: float = 0.0
    mfe: float = 0.0
    mae: float = 0.0
    _mfe_init: bool = False

    @property
    def avg_entry(self) -> float:
        return self.cost / self.qty if self.qty > 0 else 0.0

    @property
    def stop_price(self) -> float | None:
        return self.avg_entry * (1 - self.stop_pct) if self.stop_pct else None

    @property
    def target_price(self) -> float | None:
        return self.avg_entry * (1 + self.target_pct) if self.target_pct else None


def replay(
    bars: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str,
    test_start: date,
    test_end: date,
    cfg: ReplayConfig,
    *,
    profile=None,
) -> ReplayResult:
    """Replay ``symbol`` over the half-open test window ``[test_start, test_end)``.

    ``bars``/``signals`` are the **full** frames (with warm-up) so ATR-14 and any
    indicator context before ``test_start`` are available; execution is confined
    to the window. ``profile`` is required for ``sizing_mode="production"``.
    """
    start_ts = pd.Timestamp(test_start, tz="UTC")
    end_ts = pd.Timestamp(test_end, tz="UTC")
    mask = (bars.index >= start_ts) & (bars.index < end_ts)
    win = bars.loc[mask]
    ent = signals["entries"].loc[mask].to_numpy(dtype=bool)
    ext = signals["exits"].loc[mask].to_numpy(dtype=bool)
    stop_col = signals["stop_pct"].loc[mask].to_numpy() if "stop_pct" in signals else None
    target_col = signals["target_pct"].loc[mask].to_numpy() if "target_pct" in signals else None

    n = len(win)
    slip = cfg.slippage_bps / 1e4
    vpp = cfg.volume_participation_pct / 100.0
    opens = win["open"].to_numpy(dtype=float)
    highs = win["high"].to_numpy(dtype=float)
    lows = win["low"].to_numpy(dtype=float)
    closes = win["close"].to_numpy(dtype=float)
    vols = win["volume"].to_numpy(dtype=float)
    ts_index = win.index

    # Map window positions → full-frame positions (for ATR warm-up context).
    full_pos = {ts_index[j]: bars.index.get_loc(ts_index[j]) for j in range(n)}

    cash = cfg.initial_cash
    pos: _Position | None = None
    pending_signal: tuple[int, float | None, float | None, float] | None = None
    pending_exit = False
    trades: list[Trade] = []
    equity = [0.0] * n
    exposure_bars = 0

    def _commission(qty: float) -> float:
        return cfg.per_order_usd + cfg.per_share_usd * qty

    def _close(p: _Position, price: float, reason: str, ts, j: int) -> None:
        nonlocal cash
        exit_comm = _commission(p.qty)
        proceeds = p.qty * price
        cash += proceeds - exit_comm
        pnl = proceeds - (p.qty * p.avg_entry) - p.entry_commission - exit_comm
        trades.append(
            Trade(
                symbol=symbol,
                entry_ts=p.entry_ts,
                exit_ts=ts,
                entry_price=p.avg_entry,
                exit_price=price,
                qty=p.qty,
                pnl=pnl,
                mfe=p.mfe,
                mae=p.mae,
                bars_held=max(1, j - p.entry_bar + 1),
                exit_reason=reason,
                entry_commission=p.entry_commission,
                exit_commission=exit_comm,
                partial=p.target_qty > p.qty + 1e-9,
                cancelled_qty=max(0.0, p.target_qty - p.qty),
            )
        )

    for j in range(n):
        o, h, low, c, v, ts = opens[j], highs[j], lows[j], closes[j], vols[j], ts_index[j]

        # (1) market exit at open from a prior exit signal
        if pending_exit and pos is not None and pos.complete and pos.qty > 0:
            _close(pos, o * (1 - slip), "signal", ts, j)
            pos = None
            pending_exit = False

        # (2) begin/continue entry fills at open
        if pending_signal is not None and pos is None:
            sig_j, sp, tp, qty = pending_signal
            pos = _Position(target_qty=qty, stop_pct=sp, target_pct=tp, entry_bar=j)
            pending_signal = None
        if pos is not None and not pos.complete:
            remaining = pos.target_qty - pos.qty
            cap = vpp * v
            fill = min(remaining, cap) if cap > 0 else 0.0
            if fill > 1e-12:
                fill_price = o * (1 + slip)
                pos.qty += fill
                pos.cost += fill * fill_price
                cash -= fill * fill_price
                if pos.entry_ts is None:
                    pos.entry_ts = ts
                    pos.entry_bar = j
            pos.bars_filling += 1
            if pos.target_qty - pos.qty <= 1e-9:
                pos.complete = True
            elif pos.bars_filling >= _MAX_FILL_BARS:
                pos.complete = True  # cancel remainder; keep whatever filled
            if pos.complete:
                if pos.qty <= 1e-12:
                    pos = None  # nothing filled → cancel entirely
                else:
                    pos.entry_commission = _commission(pos.qty)
                    cash -= pos.entry_commission

        # (3) intra-bar stop/target on held qty
        if pos is not None and pos.qty > 0:
            _update_excursions(pos, h, low)
            exit_px, reason = _check_exit(pos, o, h, low)
            if exit_px is not None:
                _close(pos, exit_px * (1 - slip), reason, ts, j)
                pos = None

        # force-close any open position at the segment's final bar close
        if j == n - 1 and pos is not None and pos.qty > 0:
            # A position still mid-fill (entry order not finalized) never had its
            # entry commission charged — charge it now so the trade's P&L is correct.
            if not pos.complete and pos.entry_commission == 0:
                pos.entry_commission = _commission(pos.qty)
                cash -= pos.entry_commission
                pos.complete = True
            _close(pos, c * (1 - slip), "force_close", ts, j)
            pos = None

        # (4) mark equity at close
        equity[j] = cash + (pos.qty * c if pos is not None else 0.0)
        if pos is not None and pos.qty > 0:
            exposure_bars += 1

        # (5) new signals at close
        e, x = bool(ent[j]), bool(ext[j])
        if e and x:
            pass  # same-bar entry+exit → no-op (ADR-091)
        elif e and pos is None and pending_signal is None and j + 1 < n:
            sp = float(stop_col[j]) if stop_col is not None and not pd.isna(stop_col[j]) else None
            tp = float(target_col[j]) if target_col is not None and not pd.isna(target_col[j]) else None
            qty = _size_entry(bars, symbol, full_pos[ts], c, cash, sp, cfg, profile)
            if qty > 0:
                pending_signal = (j, sp, tp, qty)
        elif x and pos is not None and pos.complete:
            pending_exit = True

    eq_series = pd.Series(equity, index=ts_index, name="equity", dtype="float64")
    return ReplayResult(
        symbol=symbol, equity=eq_series, trades=trades,
        exposure_bars=exposure_bars, n_bars=n,
    )


def _update_excursions(p: _Position, high: float, low: float) -> None:
    fav = high - p.avg_entry
    adv = low - p.avg_entry
    if not p._mfe_init:
        p.mfe, p.mae, p._mfe_init = fav, adv, True
    else:
        p.mfe = max(p.mfe, fav)
        p.mae = min(p.mae, adv)


def _check_exit(p: _Position, o: float, high: float, low: float):
    """Return ``(exit_price_before_slippage, reason)`` or ``(None, "")``.

    Gap-through fills at the open. Same-bar stop+target → stop first."""
    stop = p.stop_price
    target = p.target_price
    stop_hit = stop is not None and low <= stop
    target_hit = target is not None and high >= target
    if stop_hit:
        # gap-through: if the bar opened below the stop, fill at the open
        return (min(o, stop), "stop")
    if target_hit:
        return (max(o, target), "target")
    return (None, "")


def _size_entry(bars, symbol, full_pos, price, equity, stop_pct, cfg, profile) -> float:
    """Qty for a new entry. ``fixed_qty_1`` → 1 share; ``production`` → the same
    ``compute_size`` used by ``process_alert`` (AC-09-12)."""
    if cfg.sizing_mode != "production":
        return 1.0
    if profile is None:
        return 0.0
    atr14 = atr14_from_bars(bars, full_pos)
    stop_distance = Decimal(str(price)) * Decimal(str(stop_pct)) if stop_pct else None
    inp = build_sizing_inputs(
        symbol=symbol,
        price=Decimal(str(price)),
        equity=Decimal(str(equity)),
        atr14=atr14,
        stop_distance=stop_distance,
    )
    result = compute_size(inp, profile)
    return float(result.qty) if result.ok else 0.0
