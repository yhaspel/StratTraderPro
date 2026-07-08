"""Server-side report label dictionary (M09 §13).

Report copy (PDF/HTML section titles, metric names, the disclaimer, the PBO
warning) is keyed by language, default ``en`` — the structure is locale-ready but
only ``en`` is populated today. The **disclaimer is non-removable**: it lives
here and is baked into the template flow, never sourced from run config or
caller-supplied context.
"""
from __future__ import annotations

LABELS = {
    "en": {
        "title": "Walk-Forward Backtest Tearsheet",
        "cover": "Cover",
        "config": "Configuration",
        "strategy": "Strategy",
        "range": "Date range",
        "symbols": "Symbols",
        "generated": "Generated",
        "disclaimer_title": "Important — Past Performance Disclaimer",
        "disclaimer": (
            "Past performance is not indicative of future results. This tearsheet "
            "is a historical simulation on the strategy and cost assumptions shown "
            "and does not represent actual trading. Simulated results have inherent "
            "limitations, do not account for all real-world frictions (liquidity, "
            "borrow, halts, corporate actions), and can be over-fit to the sample. "
            "Nothing here is investment advice. Do not trade capital you cannot "
            "afford to lose."
        ),
        "pbo_badge_high": "HIGH OVERFITTING RISK",
        "pbo_badge_ok": "Overfitting risk within range",
        "pbo_warning": (
            "Probability of Backtest Overfitting (PBO) exceeds 0.5 — the in-sample "
            "best parameters tend to underperform out-of-sample. Treat these "
            "results as unreliable."
        ),
        "pbo_insufficient": "Insufficient trials for an overfit estimate (PBO not computed).",
        "sec_equity": "Out-of-Sample Equity Curve",
        "sec_drawdown": "Drawdown",
        "sec_heatmap": "Monthly Returns (%)",
        "sec_windows": "Per-Window Sharpe",
        "sec_trades": "Top Trades by |P&L|",
        "sec_metrics": "Performance Metrics",
        "cost_summary": "Cost model",
        "sizing_mode": "Sizing",
        "sizing_production": "Production sizing (regime/sentiment neutralized)",
        "sizing_fixed": "Fixed qty 1",
        # metric display names (AC-09-6)
        "m_total_return": "Total return",
        "m_cagr": "CAGR",
        "m_sharpe": "Sharpe",
        "m_sortino": "Sortino",
        "m_mar": "MAR",
        "m_max_drawdown": "Max drawdown",
        "m_win_pct": "% win",
        "m_profit_factor": "Profit factor",
        "m_avg_win": "Avg win",
        "m_avg_loss": "Avg loss",
        "m_expectancy": "Expectancy",
        "m_exposure_pct": "Exposure %",
        "m_turnover": "Turnover",
        "m_trade_count": "Trades",
        "m_pbo": "PBO",
        "m_sharpe_stability": "Sharpe stability (mean/σ)",
    }
}


def get_labels(lang: str = "en") -> dict:
    return LABELS.get(lang, LABELS["en"])
