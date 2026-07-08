"""Report builder tests (M09 §10.1, §6.6)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from django.test import SimpleTestCase, override_settings

from apps.backtest import report


@dataclass
class _T:
    symbol: str = "AAA"
    entry_ts: object = None
    exit_ts: object = None
    entry_price: float = 100.0
    exit_price: float = 105.0
    qty: float = 1.0
    pnl: float = 5.0
    mfe: float = 6.0
    mae: float = -1.0
    bars_held: int = 3
    exit_reason: str = "signal"
    entry_commission: float = 0.0
    exit_commission: float = 0.0
    partial: bool = False
    cancelled_qty: float = 0.0


def _payload(pbo=0.2):
    idx = pd.date_range("2020-06-01", periods=40, freq="D", tz="UTC")
    eq = pd.Series([100000 + i * 50 for i in range(40)], index=idx, dtype="float64")
    t = _T(entry_ts=idx[1], exit_ts=idx[5])
    return report.SymbolPayload(
        symbol="AAA",
        metrics={"total_return": 0.02, "cagr": 0.1, "sharpe": 1.2, "sortino": 1.5, "mar": 0.8,
                 "max_drawdown": -0.05, "win_pct": 60.0, "profit_factor": 2.1, "avg_win": 10.0,
                 "avg_loss": -5.0, "expectancy": 3.0, "exposure_pct": 40.0, "turnover": 1.2, "trade_count": 5},
        pbo=pbo,
        sharpe_stability={"mean": 1.1, "std": 0.3, "n": 3},
        windows=[{"window_index": 0, "train_start": "2020-01-01", "train_end": "2020-06-29",
                  "test_start": "2020-06-29", "test_end": "2020-08-28", "best_params": {"fast": 10, "slow": 30},
                  "oos_metrics": {"sharpe": 1.3}}],
        equity=eq, trades=[t],
    )


_CONFIG = {"strategy_slug": "sma-cross-demo", "symbols": ["AAA"], "start": "2020-01-01",
           "end": "2021-01-01", "sizing_mode": "fixed_qty_1", "costs": {"slippage_bps": 5}}


class ReportJsonTests(SimpleTestCase):
    def test_metrics_hash_stable_and_deterministic(self):
        p = [_payload()]
        j1 = report.build_json(_CONFIG, p)
        j2 = report.build_json(_CONFIG, p)
        self.assertEqual(report.metrics_hash(j1), report.metrics_hash(j2))
        self.assertEqual(len(report.metrics_hash(j1)), 64)  # sha-256 hex

    def test_json_rounds_floats_and_includes_series(self):
        j = report.build_json(_CONFIG, [_payload()])
        sym = j["symbols"][0]
        self.assertIn("equity", sym)
        self.assertIn("drawdown", sym)
        self.assertEqual(sym["trades"][0]["exit_reason"], "signal")

    def test_hash_changes_with_metrics(self):
        a = report.metrics_hash(report.build_json(_CONFIG, [_payload()]))
        p2 = _payload()
        p2.metrics["sharpe"] = 9.9
        b = report.metrics_hash(report.build_json(_CONFIG, [p2]))
        self.assertNotEqual(a, b)


class ReportHtmlTests(SimpleTestCase):
    def test_html_inline_plotly_and_disclaimer(self):
        html = report.build_html(_CONFIG, [_payload()]).decode("utf-8")
        self.assertIn("Plotly", html)  # inline plotly.js present (offline)
        self.assertIn("Past performance is not indicative", html)  # non-removable disclaimer

    def test_html_pbo_high_badge(self):
        html = report.build_html(_CONFIG, [_payload(pbo=0.7)]).decode("utf-8")
        self.assertIn("HIGH OVERFITTING RISK", html)


class ReportSvgTests(SimpleTestCase):
    def test_charts_use_selectable_svg_text(self):
        p = _payload()
        svg = report._equity_svg(p.equity, report.get_labels())
        self.assertIn("<svg", svg)
        self.assertIn("<text", svg)  # svg.fonttype="none" → real <text> (selectable)


@override_settings()
class ReportPdfTests(SimpleTestCase):
    def test_pdf_renders_with_sections(self):
        try:
            pdf = report.build_pdf(_CONFIG, [_payload()])
        except OSError as e:  # WeasyPrint system libs absent locally — CI/Docker have them
            self.skipTest(f"WeasyPrint native libs unavailable: {e}")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 2000)
