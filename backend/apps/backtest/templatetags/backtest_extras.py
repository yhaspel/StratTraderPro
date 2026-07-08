"""Template helpers for the PDF tearsheet (M09 §6.6)."""
from __future__ import annotations

import json

from django import template

register = template.Library()


@register.filter
def jsondump(value) -> str:
    """Compact JSON of a dict/list — used for per-window param cells."""
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)
