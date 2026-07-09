"""Dashboard websocket consumer (M04 §6.6).

``/ws/dashboard/`` — authenticated with a JWT access token on the query string
(``?token=...``) plus MFA enforcement (the same bar as ``/api/v1/*``). Each
connection joins a per-user group ``dashboard.user.{user_id}`` and receives:
``order.created``, ``order.updated``, ``fill.created``, ``position.updated``,
``broker.status``.

Events are fanned out from sync code via :func:`apps.dashboard.events.push_to_user`.
"""
from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger(__name__)

# Close codes (application-defined, 4000-4999 range).
CLOSE_UNAUTHENTICATED = 4401
CLOSE_MFA_REQUIRED = 4403


def group_name(user_id) -> str:
    return f"dashboard.user.{user_id}"


class DashboardConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # ``mfa_enabled`` is evaluated inside the sync auth method — it hits the
        # DB, which must not happen in this async context.
        user, mfa_ok, is_impersonation = await self._authenticate()
        # M10 — read-only impersonation tokens never reach the realtime socket.
        if is_impersonation:
            await self.close(code=CLOSE_MFA_REQUIRED)
            return
        if user is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        if not mfa_ok:
            await self.close(code=CLOSE_MFA_REQUIRED)
            return
        self.user = user
        self.group = group_name(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await self.send_json({"type": "connection.ack", "data": {"user_id": str(user.id)}})

    async def disconnect(self, code):
        group = getattr(self, "group", None)
        if group is not None:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # Client heartbeat: reply to keep the connection warm.
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def dashboard_event(self, event):
        """Handler for group_send messages with type ``dashboard.event``."""
        await self.send_json(event["payload"])

    # -- auth ---------------------------------------------------------------
    @database_sync_to_async
    def _authenticate(self):
        """Return ``(user, mfa_ok, is_impersonation)``. Both DB-touching
        evaluations (user lookup and the ``mfa_enabled`` property) happen here in
        sync context."""
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        from apps.users.models import User

        token = self._token_from_scope()
        if not token:
            return None, False, False
        try:
            access = AccessToken(token)
        except TokenError:
            return None, False, False
        if access.get("purpose") == "impersonation":
            return None, False, True
        user_id = access.get("user_id")
        if not user_id:
            return None, False, False
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            return None, False, False
        return user, bool(user.mfa_enabled), False

    def _token_from_scope(self) -> str | None:
        query_string = self.scope.get("query_string", b"").decode("utf-8", "ignore")
        for part in query_string.split("&"):
            if part.startswith("token="):
                return part[len("token="):]
        # Fall back to an Authorization header if present (dev convenience).
        for name, value in self.scope.get("headers", []):
            if name == b"authorization":
                raw = value.decode("utf-8", "ignore")
                if raw.lower().startswith("bearer "):
                    return raw[7:]
        return None
