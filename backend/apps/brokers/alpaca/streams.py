"""TradingStream wrapper used by run_broker_streams (M04 §6.5).

Wraps Alpaca's blocking ``TradingStream.run()`` asyncio loop. Each
``trade_updates`` event is normalized (``mapping.map_trade_update``) and handed
to an injected ``on_event`` callback — the supervisor forwards it to
``publish_fill``. The wrapper is DB-free; persistence happens downstream.
"""
from __future__ import annotations

import logging

from ..base import BrokerContext, FillEvent
from . import mapping

logger = logging.getLogger(__name__)


class AlpacaStream:
    def __init__(self, ctx: BrokerContext, *, on_event, stream=None):
        self.ctx = ctx
        self._on_event = on_event
        self._stream = stream

    def _build_stream(self):
        from alpaca.trading.stream import TradingStream

        return TradingStream(self.ctx.api_key_id, self.ctx.api_secret, paper=True)

    async def _handler(self, data):
        try:
            event: FillEvent = mapping.map_trade_update(data)
            self._on_event(self.ctx.user_id, event)
        except Exception:  # pragma: no cover — a bad event must not kill the loop
            logger.exception("alpaca.stream.handler_error", extra={"account": self.ctx.account_id})

    def run(self):  # pragma: no cover — blocking network loop, exercised live
        if self._stream is None:
            self._stream = self._build_stream()
        self._stream.subscribe_trade_updates(self._handler)
        self._stream.run()

    def stop(self):  # pragma: no cover — live teardown
        if self._stream is not None:
            try:
                self._stream.stop()
            except Exception:
                logger.debug("alpaca.stream.stop_error")
