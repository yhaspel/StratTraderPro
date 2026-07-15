"""M11 §7.4 — force ``FakeBrokerAdapter`` for load tests (frozen decision §4.1).

Why this exists
---------------
``apps.brokers.services.build_adapter`` only knows ``ALPACA`` and
``TRADESTATION``; there is **no runtime seam** that routes a webhook-driven
order to the deterministic in-memory ``FakeBrokerAdapter``. Real Alpaca paper
caps at ~200 req/min and cannot absorb 20 orders/sec, so the load test must not
touch it.

This module monkeypatches ``build_adapter`` (and the streams supervisor's use of
it) to return a ``FakeBrokerAdapter`` for any ``BrokerAccount``, WITHOUT editing
tracked application code. It is activated three ways, all documented in the
README:

  1. Server-side runners (``flatten_50.py``) call :func:`patch_build_adapter`
     directly after ``django.setup()`` — patches that one process.
  2. A **dedicated** load-test compose stack sets ``STP_LOADTEST_FAKE_BROKER=1``
     and ``PYTHONPATH=/app/loadtest`` on the ``backend``/``worker``/``streams``
     services; ``sitecustomize.py`` (next to this file) then calls
     :func:`patch_build_adapter` right after Django's app registry finishes
     loading, in every process.
  3. NEVER on the shared dev stack — it changes order execution globally.

The FakeBrokerAdapter writes scripted fills to the same transport
(``apps.orders.fills.publish_fill``) as the real adapter, so ingest→submit and
the fill→position→WS path are exercised identically (M04 §6.1).

The single equivalent production-code change M11's app owner may prefer instead
is a three-line env branch at the top of ``build_adapter`` — see the README
"FakeBrokerAdapter seam" section for the exact diff. This module is the
zero-touch alternative that keeps writes inside ``backend/loadtest/``.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("loadtest.fake_broker")

_PATCHED = False


def _build_fake(account):
    """Construct a FakeBrokerAdapter bound to the account's real ids so fills and
    positions attribute to the right user (mirrors m04_testutils.fake_factory).

    When ``STP_LOADTEST_FAKE_SEED_POSITION=1`` the adapter starts holding one
    open long position, so an L1 ``flatten_all`` actually submits a closing order
    (the AC-11-4 scenario). Left off for the webhook-order scenario so position
    reconciliation stays clean."""
    from decimal import Decimal

    from apps.brokers.base import BrokerContext, PositionDTO, Side
    from apps.brokers.fake import FakeBrokerAdapter

    adapter = FakeBrokerAdapter(
        # Mirror the real build_adapter (brokers.services): the account row is the
        # single source of truth for execution mode. Threading mode here is what
        # makes the M13 gate-2 LIVE run actually carry BrokerAccount.mode=LIVE
        # through to BrokerContext.mode — without it a "LIVE" run silently falls
        # back to the PAPER default and proves nothing about the mode plumbing.
        BrokerContext(account_id=str(account.id), user_id=str(account.user_id),
                      mode=account.mode),
        # A generous default so 20 rps of market orders always fill deterministically.
        buying_power="100000000",
        equity="100000000",
    )
    if os.environ.get("STP_LOADTEST_FAKE_SEED_POSITION") == "1":
        adapter._positions["AAPL"] = PositionDTO(
            symbol="AAPL", qty=Decimal("100"), avg_cost=Decimal("100"),
            market_price=Decimal("100"), side=Side.BUY,
        )
    if os.environ.get("STP_LOADTEST_FAKE_5XX") == "1":
        # AC-11-§7.5 Day-4 drill (alpaca-5xx-storm.sh): every place_order raises
        # BrokerError(UNAVAILABLE), simulating an Alpaca REST 5xx storm so the
        # platform's bounded-failure path (max_retries=0 → REJECTED, no retry
        # storm, no duplicate order) can be exercised without a live broker.
        from apps.brokers.errors import BrokerError, BrokerErrorCode

        def _raise_5xx(req, client_order_id):  # noqa: ANN001
            raise BrokerError(BrokerErrorCode.UNAVAILABLE, "loadtest fake 5xx storm")

        adapter.place_order = _raise_5xx  # type: ignore[assignment]
    return adapter


def patch_build_adapter() -> bool:
    """Replace ``apps.brokers.services.build_adapter`` in-process. Idempotent.

    Returns True if the patch was applied (or already active), False on import
    failure (Django not yet set up)."""
    global _PATCHED
    if _PATCHED:
        return True
    try:
        from apps.brokers import services as svc
    except Exception:  # noqa: BLE001 — called before django.setup(); caller retries
        return False

    svc.build_adapter = _build_fake  # type: ignore[assignment]
    # NOTE: the original claim that patching build_adapter also covers the streams
    # supervisor is WRONG. StreamSupervisor._build_stream (apps/brokers/streams.py)
    # instantiates AlpacaStream DIRECTLY — it never calls build_adapter — so on a
    # load stack with fake/bogus-cred accounts run_broker_streams storms the REAL
    # Alpaca paper websocket (429s, pegged CPU). Neutralise that path too so the
    # seam is actually self-contained (and AC-11-6's heartbeat semantics stay valid
    # without touching a real broker).
    _patch_streams()
    _PATCHED = True
    logger.warning("loadtest.fake_broker.patched build_adapter -> FakeBrokerAdapter")
    return True


def _patch_streams() -> None:
    """Replace StreamSupervisor._build_stream with a quiet in-memory stream that
    never connects to Alpaca. It blocks (0% CPU) representing a healthy, idle
    stream, so run_forever's touch_heartbeat keeps the account CONNECTED until the
    process is stopped — exactly the state AC-11-6 (streams-kill) drills against."""
    try:
        from apps.brokers import streams as st
    except Exception:  # noqa: BLE001 — django not set up yet; caller retries
        return

    import threading

    class _IdleStream:  # pragma: no cover — infra glue
        def run(self):
            # Block until the process is torn down. No sockets, no polling.
            threading.Event().wait()

    def _fake_build_stream(self, account):  # noqa: ANN001
        return _IdleStream()

    st.StreamSupervisor._build_stream = _fake_build_stream  # type: ignore[assignment]
    logger.warning("loadtest.fake_broker.patched StreamSupervisor._build_stream -> IdleStream")


def maybe_patch_from_env() -> bool:
    """Patch only when ``STP_LOADTEST_FAKE_BROKER=1``. Used by sitecustomize."""
    if os.environ.get("STP_LOADTEST_FAKE_BROKER") != "1":
        return False
    return patch_build_adapter()
