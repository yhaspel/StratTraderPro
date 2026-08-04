"""Backtest error codes + a single carrier exception (M09 §6.7).

Worker code raises :class:`BacktestError` with one of the ``BACKTEST_*`` codes;
the orchestrator maps it onto ``run.error_code`` / ``run.error_message`` and the
API layer maps it onto the ``{"error": {"code", "message"}}`` envelope.
"""
from __future__ import annotations

# ---- error codes (mirrored in the frontend + OpenAPI docs) -----------------
NO_ADAPTER = "BACKTEST_NO_ADAPTER"
INSUFFICIENT_DATA = "BACKTEST_INSUFFICIENT_DATA"
LIMIT_CONCURRENT = "BACKTEST_LIMIT_CONCURRENT"
GRID_TOO_LARGE = "BACKTEST_GRID_TOO_LARGE"
REPORT_TOO_LARGE = "BACKTEST_REPORT_TOO_LARGE"
TIME_CAP = "BACKTEST_TIME_CAP"
DISABLED = "BACKTEST_DISABLED"
VALIDATION = "VALIDATION_ERROR"
SWEEP_UNAVAILABLE = "BACKTEST_SWEEP_UNAVAILABLE"


class BacktestError(Exception):
    """Carries a machine code + human message from engine/worker code."""

    def __init__(self, code: str, message: str = "", *, details=None):
        self.code = code
        self.message = message or code
        self.details = details or {}
        super().__init__(f"{code}: {self.message}")
