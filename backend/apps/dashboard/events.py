"""Fan-out helpers to push realtime events to a user's dashboard group (M04).

Called from sync code (Celery tasks, services). Safe to call when Channels has
no configured layer (returns quietly) so unit tests that don't assert on WS
don't need a layer.
"""
from __future__ import annotations

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .consumers import group_name

logger = logging.getLogger(__name__)

# Event type constants (mirrored in the frontend ws.service).
ORDER_CREATED = "order.created"
ORDER_UPDATED = "order.updated"
FILL_CREATED = "fill.created"
POSITION_UPDATED = "position.updated"
BROKER_STATUS = "broker.status"


def push_to_user(user_id, event_type: str, data: dict) -> None:
    """Send ``{type, data}`` to every open dashboard socket for ``user_id``."""
    layer = get_channel_layer()
    if layer is None:  # pragma: no cover — only when CHANNEL_LAYERS unset
        return
    payload = {"type": event_type, "data": data}
    try:
        async_to_sync(layer.group_send)(
            group_name(user_id),
            {"type": "dashboard.event", "payload": payload},
        )
    except Exception:  # pragma: no cover — never let a WS push break the caller
        logger.warning("dashboard.push.failed", extra={"event_type": event_type})
