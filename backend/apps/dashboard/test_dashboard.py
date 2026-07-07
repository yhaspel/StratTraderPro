"""M04 — Dashboard websocket consumer (JWT + MFA auth, realtime fan-out).

AC-04-8: a position update reaches the socket in real time. Uses the in-memory
channel layer (test settings). Each test runs its whole scenario inside a single
coroutine (one event loop) so the websocket task survives across steps. Tokens
and users are created in sync context before entering the loop.
``TransactionTestCase`` so the consumer's threaded DB queries see the setUp rows.
"""
from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from apps.dashboard.consumers import group_name
from apps.dashboard.events import POSITION_UPDATED
from apps.m04_testutils import access_token, create_user
from config.asgi import application


def _comm(token):
    q = f"?token={token}" if token else ""
    return WebsocketCommunicator(application, f"/ws/dashboard/{q}")


class DashboardConsumerTests(TransactionTestCase):
    def test_connect_with_valid_token(self):
        token = access_token(create_user())

        async def scenario():
            comm = _comm(token)
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            ack = await comm.receive_json_from()
            self.assertEqual(ack["type"], "connection.ack")
            await comm.disconnect()

        async_to_sync(scenario)()

    def test_reject_without_token(self):
        async def scenario():
            comm = _comm(None)
            connected, _ = await comm.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()

    def test_reject_without_mfa(self):
        token = access_token(create_user(email="nomfa@example.com", mfa=False))

        async def scenario():
            comm = _comm(token)
            connected, _ = await comm.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()

    def test_receives_position_update(self):
        user = create_user()
        token = access_token(user)
        group = group_name(user.id)

        async def scenario():
            comm = _comm(token)
            connected, _ = await comm.connect()
            self.assertTrue(connected)
            await comm.receive_json_from()  # drain ack
            layer = get_channel_layer()
            await layer.group_send(
                group,
                {"type": "dashboard.event", "payload": {"type": POSITION_UPDATED, "data": {"symbol": "AAPL"}}},
            )
            msg = await comm.receive_json_from()
            self.assertEqual(msg["type"], POSITION_UPDATED)
            self.assertEqual(msg["data"]["symbol"], "AAPL")
            await comm.disconnect()

        async_to_sync(scenario)()

    def test_ping_pong(self):
        token = access_token(create_user())

        async def scenario():
            comm = _comm(token)
            await comm.connect()
            await comm.receive_json_from()  # ack
            await comm.send_json_to({"type": "ping"})
            msg = await comm.receive_json_from()
            self.assertEqual(msg["type"], "pong")
            await comm.disconnect()

        async_to_sync(scenario)()
