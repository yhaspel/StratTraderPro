"""Backtest realtime events (M09 §6.8).

Streamed over the **existing** ``/ws/dashboard/`` socket via
``apps.dashboard.events.push_to_user``. Stages: queued/loading/sweeping/
replaying/reporting; terminal: completed/failed/cancelled.
"""
from __future__ import annotations

from apps.dashboard.events import push_to_user

PROGRESS = "backtest.progress"
COMPLETED = "backtest.completed"
FAILED = "backtest.failed"
CANCELLED = "backtest.cancelled"


def push_progress(user_id, run_id, pct: int, stage: str, eta_seconds: float | None) -> None:
    push_to_user(user_id, PROGRESS, {
        "run_id": str(run_id), "pct": int(pct), "stage": stage,
        "eta_seconds": None if eta_seconds is None else round(float(eta_seconds), 1),
    })


def push_terminal(user_id, run_id, event_type: str, extra: dict | None = None) -> None:
    data = {"run_id": str(run_id)}
    if extra:
        data.update(extra)
    push_to_user(user_id, event_type, data)
