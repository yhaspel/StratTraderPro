#!/usr/bin/env python3
"""
M04 Day-1 SPIKE — IB Gateway sidecar smoke test.

Goal: prove the four assumptions in docs/adr/040-ibkr-gateway-sidecar.md by
exercising the full happy path against a running ib-gateway container:

    1. Connect via ib_insync to the Gateway's API port.
    2. Read account summary (proves login + entitlements).
    3. Place 1-share AAPL paper market order, capture the OrderAck.
    4. Wait for execDetailsEvent to fire — capture the Fill.
    5. Force-disconnect, reconnect, confirm the same client_id can re-bind.

Exit codes:
    0   all five steps passed
    1   connect failed (assumption 1/2 dead)
    2   account/positions read failed (login worked, API perms wrong)
    3   place_order rejected or no ack within timeout
    4   no fill within timeout (paper market closed? wrong contract?)
    5   reconnect failed (assumption 3 dead — adapter can't recover)

Usage (after `docker compose --profile ibkr-spike up -d ib-gateway`):

    pip install ib_insync==0.9.86
    python scripts/spike_ibkr_smoke.py \
        --host localhost --port 4002 --client-id 7

Arguments default to the values in docker-compose.yml.

Run during US market hours for a real fill; outside hours the order will
sit in PreSubmitted state and step 4 will time out — that's still useful
data (proves the connect/place path works) but not a full pass.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass

try:
    from ib_insync import IB, MarketOrder, Stock, util
except ImportError:
    print("ERROR: pip install ib_insync==0.9.86", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Exit codes — keep in sync with the docstring above.
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_CONNECT = 1
EXIT_ACCOUNT = 2
EXIT_PLACE = 3
EXIT_FILL = 4
EXIT_RECONNECT = 5


@dataclass
class SpikeResult:
    """Pretty-printed at the end so the runbook has copy-pasteable evidence."""

    connect_ok: bool = False
    account_summary_keys: int = 0
    order_status_after_place: str = ""
    broker_order_id: int = 0
    fill_count: int = 0
    fill_price: float = 0.0
    reconnect_ok: bool = False
    cold_start_seconds: float = 0.0


def _connect_with_retry(
    ib: IB, host: str, port: int, client_id: int, timeout: int
) -> float:
    """Connect, retrying every 2s until timeout. Returns elapsed seconds."""
    log = logging.getLogger("spike")
    started = time.monotonic()
    deadline = started + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            ib.connect(host, port, clientId=client_id, timeout=10)
            elapsed = time.monotonic() - started
            log.info("connected in %.1fs", elapsed)
            return elapsed
        except Exception as exc:  # ib_insync raises a grab-bag of types
            last_err = exc
            log.info("connect attempt failed (%s); retrying", exc.__class__.__name__)
            time.sleep(2)
    raise RuntimeError(f"connect timed out after {timeout}s; last error: {last_err}")


def run_spike(host: str, port: int, client_id: int, connect_timeout: int) -> SpikeResult:
    """Execute the full smoke. Raises on the first failed step."""
    log = logging.getLogger("spike")
    result = SpikeResult()
    ib = IB()

    # --- Step 1: connect ----------------------------------------------------
    log.info("STEP 1: connect to %s:%s clientId=%s", host, port, client_id)
    try:
        result.cold_start_seconds = _connect_with_retry(
            ib, host, port, client_id, connect_timeout
        )
        result.connect_ok = True
    except Exception as exc:
        log.error("STEP 1 FAILED: %s", exc)
        sys.exit(EXIT_CONNECT)

    try:
        # --- Step 2: account summary ---------------------------------------
        log.info("STEP 2: read account summary")
        try:
            summary = ib.accountSummary()
            result.account_summary_keys = len(summary)
            log.info("account summary: %d rows", len(summary))
            for row in summary[:5]:
                log.info("  %s = %s %s", row.tag, row.value, row.currency)
        except Exception as exc:
            log.error("STEP 2 FAILED: %s", exc)
            sys.exit(EXIT_ACCOUNT)

        # --- Step 3: place 1-share AAPL MKT --------------------------------
        log.info("STEP 3: place 1-share AAPL MKT (paper)")
        contract = Stock("AAPL", "SMART", "USD")
        ib.qualifyContracts(contract)
        order = MarketOrder("BUY", 1)
        trade = ib.placeOrder(contract, order)

        # Wait up to 15s for an ack (status leaves "PendingSubmit").
        ack_deadline = time.monotonic() + 15
        while time.monotonic() < ack_deadline:
            ib.sleep(0.5)
            if trade.orderStatus.status not in ("", "PendingSubmit"):
                break
        result.order_status_after_place = trade.orderStatus.status
        result.broker_order_id = trade.order.orderId
        log.info(
            "order ack: status=%s brokerOrderId=%s",
            result.order_status_after_place, result.broker_order_id,
        )
        if not result.order_status_after_place:
            log.error("STEP 3 FAILED: no ack within 15s")
            sys.exit(EXIT_PLACE)
        if result.order_status_after_place in ("Cancelled", "ApiCancelled"):
            log.error("STEP 3 FAILED: order rejected / cancelled")
            sys.exit(EXIT_PLACE)

        # --- Step 4: wait for fill -----------------------------------------
        log.info("STEP 4: wait for fill (60s timeout — outside RTH this will time out)")
        fill_deadline = time.monotonic() + 60
        while time.monotonic() < fill_deadline:
            ib.sleep(0.5)
            if trade.fills:
                break
        result.fill_count = len(trade.fills)
        if result.fill_count == 0:
            log.warning(
                "STEP 4 NO-FILL: order accepted but no fill in 60s. "
                "Likely outside US RTH or symbol halted. "
                "Connect/place path is proven; rerun during market hours."
            )
            sys.exit(EXIT_FILL)
        result.fill_price = float(trade.fills[0].execution.price)
        log.info(
            "fill captured: qty=%s price=%s execId=%s",
            trade.fills[0].execution.shares,
            result.fill_price,
            trade.fills[0].execution.execId,
        )

        # --- Step 5: forced reconnect --------------------------------------
        # Disconnect, wait, reconnect with the SAME client_id. If IB Gateway
        # holds onto the prior session's reservation we'll get a "client id
        # already in use" error — that's the failure we're hunting for.
        log.info("STEP 5: disconnect + reconnect on same clientId")
        ib.disconnect()
        time.sleep(3)
        try:
            ib.connect(host, port, clientId=client_id, timeout=15)
            result.reconnect_ok = True
            log.info("reconnect OK")
        except Exception as exc:
            log.error("STEP 5 FAILED: %s", exc)
            sys.exit(EXIT_RECONNECT)
    finally:
        if ib.isConnected():
            ib.disconnect()

    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=4002, help="paper=4002, live=4001")
    p.add_argument("--client-id", type=int, default=7,
                   help="any int 1-32; pick something unique per concurrent connection")
    p.add_argument("--connect-timeout", type=int, default=180,
                   help="seconds to wait for first connect (cold start can be 60-120s)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if args.verbose:
        util.logToConsole(logging.DEBUG)

    result = run_spike(args.host, args.port, args.client_id, args.connect_timeout)

    print("\n" + "=" * 60)
    print("SPIKE RESULT — copy this into the ADR's Findings section")
    print("=" * 60)
    print(f"  cold_start_seconds        = {result.cold_start_seconds:.1f}")
    print(f"  connect_ok                = {result.connect_ok}")
    print(f"  account_summary_keys      = {result.account_summary_keys}")
    print(f"  broker_order_id           = {result.broker_order_id}")
    print(f"  order_status_after_place  = {result.order_status_after_place}")
    print(f"  fill_count                = {result.fill_count}")
    print(f"  fill_price                = {result.fill_price}")
    print(f"  reconnect_ok              = {result.reconnect_ok}")
    print("=" * 60)
    print("ALL STEPS PASSED — assumptions 1-3 proven for this topology.")
    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()
