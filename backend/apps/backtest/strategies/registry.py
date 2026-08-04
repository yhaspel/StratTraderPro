"""Adapter registry (M09 §6.1).

Maps ``slug -> adapter class``. Adapters register via the ``@register``
module-level decorator. **Repo-owned code only** — the M03 ``load_strategies``
import path never ingests adapter code (ADR-092 security stance); an uploaded or
community strategy without a registered adapter simply cannot be backtested
(lookup returns ``None`` → 400 ``BACKTEST_NO_ADAPTER`` + a UI banner).
"""
from __future__ import annotations

from .base import BacktestStrategy

_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    """Class decorator: register an adapter under its ``slug`` attribute."""
    slug = getattr(cls, "slug", None)
    if not slug:
        raise ValueError(f"Adapter {cls!r} has no slug.")
    if slug in _REGISTRY and _REGISTRY[slug] is not cls:
        raise ValueError(f"Duplicate backtest adapter slug: {slug!r}")
    _REGISTRY[slug] = cls
    return cls


def get_adapter(slug: str) -> BacktestStrategy | None:
    """Return an *instance* of the adapter for ``slug``, or ``None`` if none is
    registered."""
    cls = _REGISTRY.get(slug)
    return cls() if cls is not None else None


def registered_slugs() -> list[str]:
    return sorted(_REGISTRY)
