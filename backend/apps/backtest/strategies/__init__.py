"""Strategy adapter package (M09 §6.1).

Importing the package registers all bundled adapters (their ``@register``
decorators run on import), so ``get_adapter`` / ``registered_slugs`` see them.
"""
from __future__ import annotations

from . import sma_cross  # noqa: F401 — import for @register side effect
from .registry import get_adapter, register, registered_slugs

__all__ = ["get_adapter", "register", "registered_slugs"]
