"""Tearsheet builders (M09 §6.6).

Three artifacts from one set of per-symbol payloads:

- **JSON** — canonical (sorted keys, floats rounded 1e-9), the hashable source of
  ``metrics_hash`` (reproducibility DoD).
- **HTML** — single-file Plotly with ``include_plotlyjs="inline"`` (fully offline).
- **PDF** — WeasyPrint from a Django template; charts rendered server-side by
  matplotlib to **SVG** with ``svg.fonttype="none"`` (selectable text, not raster).
  A non-removable disclaimer + a PBO warning badge (when PBO > 0.5). No kaleido.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .i18n import get_labels
from .stats import drawdown_series

PBO_WARN_THRESHOLD = 0.5


@dataclass
class SymbolPayload:
    symbol: str
    metrics: dict
    pbo: float | None
    sharpe_stability: dict
    windows: list[dict] = field(default_factory=list)
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype="float64"))
    trades: list = field(default_factory=list)


@dataclass
class ReportBundle:
    json_dict: dict
    metrics_hash: str
    html: bytes
    pdf: bytes


# ---------------------------------------------------------------------------
# Canonical JSON + hash
# ---------------------------------------------------------------------------
def _canon(o):
    if isinstance(o, bool):
        return o
    if isinstance(o, (np.floating, float)):
        r = round(float(o), 9)
        return 0.0 if r == 0 else r
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, dict):
        return {str(k): _canon(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_canon(v) for v in o]
    return o


def metrics_hash(json_dict: dict) -> str:
    canon = _canon(json_dict)
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _series_to_pairs(series: pd.Series) -> list[list]:
    return [[ts.isoformat(), round(float(v), 9)] for ts, v in series.items()]


def _trade_dict(t) -> dict:
    return {
        "symbol": t.symbol,
        "entry_ts": t.entry_ts.isoformat() if t.entry_ts is not None else None,
        "exit_ts": t.exit_ts.isoformat() if t.exit_ts is not None else None,
        "entry_price": round(float(t.entry_price), 9),
        "exit_price": round(float(t.exit_price), 9),
        "qty": round(float(t.qty), 9),
        "pnl": round(float(t.pnl), 9),
        "mfe": round(float(t.mfe), 9),
        "mae": round(float(t.mae), 9),
        "bars_held": int(t.bars_held),
        "exit_reason": t.exit_reason,
        "entry_commission": round(float(t.entry_commission), 9),
        "exit_commission": round(float(t.exit_commission), 9),
        "partial": bool(t.partial),
        "cancelled_qty": round(float(t.cancelled_qty), 9),
    }


def build_json(config: dict, payloads: list[SymbolPayload]) -> dict:
    """Canonical export: config, per-symbol metrics/PBO/stability, per-window table,
    OOS equity + drawdown series, full trade list."""
    symbols = []
    for p in payloads:
        dd = drawdown_series(p.equity)
        symbols.append({
            "symbol": p.symbol,
            "metrics": p.metrics,
            "pbo": p.pbo,
            "sharpe_stability": p.sharpe_stability,
            "windows": p.windows,
            "equity": _series_to_pairs(p.equity),
            "drawdown": _series_to_pairs(dd),
            "trades": [_trade_dict(t) for t in p.trades],
        })
    return {"config": config, "symbols": symbols}


# ---------------------------------------------------------------------------
# HTML report (inline Plotly)
# ---------------------------------------------------------------------------
def build_html(config: dict, payloads: list[SymbolPayload], lang: str = "en") -> bytes:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    lab = get_labels(lang)
    parts: list[str] = [_html_head(lab), _cover_html(config, payloads, lab)]
    first = True
    for p in payloads:
        dd = drawdown_series(p.equity)
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
            subplot_titles=(lab["sec_equity"], lab["sec_drawdown"]),
        )
        if len(p.equity):
            fig.add_trace(go.Scatter(x=list(p.equity.index), y=list(p.equity.values),
                                     mode="lines", name="equity"), row=1, col=1)
            fig.add_trace(go.Scatter(x=list(dd.index), y=list(dd.values),
                                     mode="lines", name="drawdown", fill="tozeroy"), row=2, col=1)
        fig.update_layout(height=520, margin=dict(l=40, r=20, t=40, b=30), showlegend=False)
        div = fig.to_html(include_plotlyjs="inline" if first else False, full_html=False)
        first = False
        parts.append(f"<h2>{html.escape(p.symbol)}</h2>")
        parts.append(_pbo_badge_html(p, lab))
        parts.append(_metrics_table_html(p, lab))
        parts.append(div)
        parts.append(_windows_table_html(p, lab))
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


def _html_head(lab) -> str:
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(lab['title'])}</title>"
        "<style>body{font-family:DejaVu Sans,Arial,sans-serif;margin:24px;color:#1a1a1a}"
        "table{border-collapse:collapse;margin:12px 0}td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px}"
        ".disclaimer{background:#fff8e1;border:1px solid #f0c000;padding:12px;margin:12px 0;font-size:12px}"
        ".badge{display:inline-block;padding:4px 10px;border-radius:4px;font-weight:bold;font-size:12px}"
        ".badge.high{background:#c62828;color:#fff}.badge.ok{background:#2e7d32;color:#fff}"
        "h1,h2{color:#0d47a1}</style></head><body>"
    )


def _cover_html(config, payloads, lab) -> str:
    syms = ", ".join(html.escape(str(s)) for s in config.get("symbols", []))
    slug = html.escape(str(config.get("strategy_slug", "")))
    start = html.escape(str(config.get("start", "")))
    end = html.escape(str(config.get("end", "")))
    disc = f"<b>{html.escape(lab['disclaimer_title'])}</b><br>{html.escape(lab['disclaimer'])}"
    return (
        f"<h1>{html.escape(lab['title'])}</h1>"
        f"<p><b>{lab['strategy']}:</b> {slug} &nbsp; "
        f"<b>{lab['range']}:</b> {start} → {end}<br>"
        f"<b>{lab['symbols']}:</b> {syms}<br>"
        f"<b>{lab['sizing_mode']}:</b> {html.escape(_sizing_label(config, lab))} &nbsp; "
        f"<b>{lab['cost_summary']}:</b> {html.escape(_cost_label(config))}</p>"
        f"<div class='disclaimer'>{disc}</div>"
    )


def _sizing_label(config, lab) -> str:
    return lab["sizing_production"] if config.get("sizing_mode") == "production" else lab["sizing_fixed"]


def _cost_label(config) -> str:
    c = config.get("costs", {})
    return (
        f"slippage {c.get('slippage_bps', 5)}bp, "
        f"per-order ${c.get('per_order_usd', 0)}, per-share ${c.get('per_share_usd', 0)}"
    )


def _pbo_badge_html(p: SymbolPayload, lab) -> str:
    if p.pbo is None:
        return f"<p><span class='badge ok'>{lab['m_pbo']}: n/a</span> {html.escape(lab['pbo_insufficient'])}</p>"
    if p.pbo > PBO_WARN_THRESHOLD:
        return (f"<p><span class='badge high'>{lab['pbo_badge_high']} — {lab['m_pbo']} {p.pbo:.2f}</span><br>"
                f"<small>{html.escape(lab['pbo_warning'])}</small></p>")
    return f"<p><span class='badge ok'>{lab['pbo_badge_ok']} — {lab['m_pbo']} {p.pbo:.2f}</span></p>"


_METRIC_ORDER = [
    ("m_total_return", "total_return", "pct"), ("m_cagr", "cagr", "pct"),
    ("m_sharpe", "sharpe", "num"), ("m_sortino", "sortino", "num"), ("m_mar", "mar", "num"),
    ("m_max_drawdown", "max_drawdown", "pct"), ("m_win_pct", "win_pct", "raw_pct"),
    ("m_profit_factor", "profit_factor", "num"), ("m_avg_win", "avg_win", "usd"),
    ("m_avg_loss", "avg_loss", "usd"), ("m_expectancy", "expectancy", "usd"),
    ("m_exposure_pct", "exposure_pct", "raw_pct"), ("m_turnover", "turnover", "num"),
    ("m_trade_count", "trade_count", "int"),
]


def _fmt(kind: str, v) -> str:
    if v is None:
        return "∞" if kind == "num" else "—"
    if kind == "pct":
        return f"{v * 100:.2f}%"
    if kind == "raw_pct":
        return f"{v:.2f}%"
    if kind == "usd":
        return f"${v:,.2f}"
    if kind == "int":
        return f"{int(v)}"
    return f"{v:.3f}"


def _metrics_table_html(p: SymbolPayload, lab) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(lab[k])}</td><td style='text-align:right'>{_fmt(kind, p.metrics.get(mk))}</td></tr>"
        for k, mk, kind in _METRIC_ORDER
    )
    stab = p.sharpe_stability
    rows += (f"<tr><td>{html.escape(lab['m_sharpe_stability'])}</td>"
             f"<td style='text-align:right'>{stab.get('mean', 0):.3f} / {stab.get('std', 0):.3f}</td></tr>")
    return f"<h3>{html.escape(lab['sec_metrics'])}</h3><table>{rows}</table>"


def _windows_table_html(p: SymbolPayload, lab) -> str:
    head = "<tr><th>#</th><th>train</th><th>test</th><th>params</th><th>Sharpe</th></tr>"
    body = "".join(
        f"<tr><td>{w['window_index']}</td>"
        f"<td>{w['train_start']}→{w['train_end']}</td>"
        f"<td>{w['test_start']}→{w['test_end']}</td>"
        f"<td>{html.escape(json.dumps(w['best_params']))}</td>"
        f"<td style='text-align:right'>{w['oos_metrics'].get('sharpe', 0):.2f}</td></tr>"
        for w in p.windows
    )
    return f"<h3>{html.escape(lab['sec_windows'])}</h3><table>{head}{body}</table>"


# ---------------------------------------------------------------------------
# PDF report (WeasyPrint + matplotlib SVG)
# ---------------------------------------------------------------------------
def build_pdf(config: dict, payloads: list[SymbolPayload], lang: str = "en") -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    from django.template.loader import render_to_string
    from weasyprint import HTML

    lab = get_labels(lang)
    sections = []
    for p in payloads:
        dd = drawdown_series(p.equity)
        top_trades = sorted(p.trades, key=lambda t: abs(t.pnl), reverse=True)[:20]
        sections.append({
            "symbol": p.symbol,
            "metrics_rows": [(lab[k], _fmt(kind, p.metrics.get(mk))) for k, mk, kind in _METRIC_ORDER],
            "sharpe_stability": p.sharpe_stability,
            "pbo": p.pbo,
            "pbo_high": p.pbo is not None and p.pbo > PBO_WARN_THRESHOLD,
            "windows": p.windows,
            "equity_svg": _equity_svg(p.equity, lab),
            "drawdown_svg": _drawdown_svg(dd, lab),
            "heatmap_svg": _heatmap_svg(p.equity, lab),
            "windows_svg": _windows_svg(p.windows, lab),
            "top_trades": [_trade_dict(t) for t in top_trades],
        })
    ctx = {
        "lab": lab,
        "config": config,
        "sizing_label": _sizing_label(config, lab),
        "cost_label": _cost_label(config),
        "symbols_label": ", ".join(str(s) for s in config.get("symbols", [])),
        "sections": sections,
    }
    rendered = render_to_string("backtest/tearsheet.html", ctx)
    return HTML(string=rendered).write_pdf()


def _new_axes(figsize=(7.2, 2.4)):
    import matplotlib
    matplotlib.rcParams["svg.fonttype"] = "none"  # real <text> → selectable in PDF
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    return plt, fig, ax


def _fig_to_svg(plt, fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    svg = buf.getvalue()
    idx = svg.find("<svg")
    return svg[idx:] if idx >= 0 else svg


def _equity_svg(equity: pd.Series, lab) -> str:
    plt, fig, ax = _new_axes()
    if len(equity):
        ax.plot(equity.index, equity.values, color="#0d47a1", linewidth=1.1)
    ax.set_title(lab["sec_equity"], fontsize=10)
    ax.grid(True, alpha=0.3)
    return _fig_to_svg(plt, fig)


def _drawdown_svg(dd: pd.Series, lab) -> str:
    plt, fig, ax = _new_axes()
    if len(dd):
        ax.fill_between(dd.index, dd.values * 100, 0, color="#c62828", alpha=0.5)
    ax.set_title(lab["sec_drawdown"], fontsize=10)
    ax.set_ylabel("%")
    ax.grid(True, alpha=0.3)
    return _fig_to_svg(plt, fig)


def _monthly_returns(equity: pd.Series) -> pd.DataFrame:
    if len(equity) < 2:
        return pd.DataFrame()
    rets = equity.pct_change().dropna()
    monthly = (1 + rets).resample("ME").prod() - 1
    df = pd.DataFrame({"y": monthly.index.year, "m": monthly.index.month, "r": monthly.values})
    return df.pivot_table(index="y", columns="m", values="r", aggfunc="first")


def _heatmap_svg(equity: pd.Series, lab) -> str:
    plt, fig, ax = _new_axes(figsize=(7.2, 2.6))
    pivot = _monthly_returns(equity)
    if not pivot.empty:
        data = pivot.to_numpy(dtype="float64") * 100
        lim = np.nanmax(np.abs(data)) if np.isfinite(data).any() else 1.0
        im = ax.imshow(data, aspect="auto", cmap="RdYlGn", vmin=-lim, vmax=lim)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels([str(c) for c in pivot.columns], fontsize=7)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([str(i) for i in pivot.index], fontsize=7)
        for yi in range(data.shape[0]):
            for xi in range(data.shape[1]):
                v = data[yi, xi]
                if np.isfinite(v):
                    ax.text(xi, yi, f"{v:.1f}", ha="center", va="center", fontsize=6)
        fig.colorbar(im, ax=ax, shrink=0.7)
    ax.set_title(lab["sec_heatmap"], fontsize=10)
    return _fig_to_svg(plt, fig)


def _windows_svg(windows: list[dict], lab) -> str:
    plt, fig, ax = _new_axes()
    if windows:
        xs = [w["window_index"] for w in windows]
        ys = [w["oos_metrics"].get("sharpe", 0.0) for w in windows]
        ax.bar(xs, ys, color=["#2e7d32" if y >= 0 else "#c62828" for y in ys])
    ax.axhline(0, color="#333", linewidth=0.6)
    ax.set_title(lab["sec_windows"], fontsize=10)
    ax.set_xlabel("window")
    ax.grid(True, alpha=0.3)
    return _fig_to_svg(plt, fig)
