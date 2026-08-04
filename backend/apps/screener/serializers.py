"""Wire shapes for the screener API (M16 §9)."""
from __future__ import annotations

from .models import ScreenRun


def _iso(value):
    return value.isoformat() if value else None


def run_summary(run: ScreenRun) -> dict:
    """List row — deliberately WITHOUT ``results`` so history stays light."""
    return {
        "id": str(run.id),
        "status": run.status,
        "degraded": run.degraded,
        "error_code": run.error_code,
        "counts": run.counts or {},
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }


def run_detail(run: ScreenRun) -> dict:
    """Full run. Carries ``desc_sha256`` (A7 — it is the DESC file's hash, not a
    hash of the criteria) and the ``criteria`` snapshot, so a past run is
    reproducible and readable without re-parsing today's description."""
    return {
        **run_summary(run),
        "desc_sha256": run.desc_sha256,
        "criteria": run.criteria or {},
        "results": run.results or [],
    }
