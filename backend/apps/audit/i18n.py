"""Server-side CSV-header label dictionary for audit export (M10 §13).

Keyed by language, default ``en`` — locale-ready but only ``en`` is populated
today (`SUPPORTED_LANGUAGES = {"en"}`). Mirrors the ``apps/backtest/i18n.py``
precedent. ``get_labels`` is keyed by the requesting admin's
``UserProfile.language``.
"""
from __future__ import annotations

LABELS = {
    "en": {
        "occurred_at": "Timestamp",
        "event_type": "Event type",
        "user_id": "User ID",
        "user_email": "User email",
        "actor_id": "Actor ID",
        "actor_email": "Actor email",
        "entity_type": "Entity type",
        "entity_id": "Entity ID",
        "ip": "IP address",
        "ua": "User agent",
        "data_before": "Before",
        "data_after": "After",
        "self_hash": "Row hash",
    }
}

# Column order for the CSV export.
COLUMNS = [
    "occurred_at",
    "event_type",
    "user_id",
    "user_email",
    "actor_id",
    "actor_email",
    "entity_type",
    "entity_id",
    "ip",
    "ua",
    "data_before",
    "data_after",
    "self_hash",
]


def get_labels(lang: str = "en") -> dict:
    return LABELS.get(lang, LABELS["en"])
