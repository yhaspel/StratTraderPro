"""alpaca_smoke — local connectivity smoke against real Alpaca paper keys.

Uses the platform-level ALPACA_PAPER_* env vars (LOCAL DEV ONLY — production
users bring their own keys via the UI). Verifies connect + get_account against
the paper endpoint; optionally places a tiny market order.

    python manage.py alpaca_smoke                # connect + account only
    python manage.py alpaca_smoke --place AAPL 1 # also place 1 share MKT DAY

This backs the §10.4 runbook (docs/runbooks/alpaca-paper-smoke.md).
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.brokers.alpaca.adapter import AlpacaAdapter
from apps.brokers.base import BrokerContext, OrderRequest, OrderType, Side, TimeInForce
from apps.brokers.errors import BrokerError


class Command(BaseCommand):
    help = "Smoke-test Alpaca paper connectivity using ALPACA_PAPER_* env vars."

    def add_arguments(self, parser):
        parser.add_argument("--place", nargs=2, metavar=("SYMBOL", "QTY"), default=None)

    def handle(self, *args, **options):
        key = getattr(settings, "ALPACA_PAPER_KEY_ID", "")
        secret = getattr(settings, "ALPACA_PAPER_SECRET_KEY", "")
        if not key or not secret:
            raise CommandError("Set ALPACA_PAPER_KEY_ID and ALPACA_PAPER_SECRET_KEY in .env first.")

        adapter = AlpacaAdapter(BrokerContext(account_id="smoke", user_id="smoke", api_key_id=key, api_secret=secret))
        try:
            info = adapter.connect()
        except BrokerError as exc:
            raise CommandError(f"connect failed: {exc.code} — {exc.message}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Connected: account={info.account_number} buying_power={info.buying_power}"
            )
        )

        if options["place"]:
            from decimal import Decimal

            symbol, qty = options["place"]
            req = OrderRequest(
                symbol=symbol.upper(),
                side=Side.BUY,
                qty=Decimal(qty),
                order_type=OrderType.MKT,
                time_in_force=TimeInForce.DAY,
            )
            try:
                ack = adapter.place_order(req, client_order_id=f"smoke-{symbol}-{qty}")
            except BrokerError as exc:
                raise CommandError(f"place_order failed: {exc.code} — {exc.message}") from exc
            self.stdout.write(
                self.style.SUCCESS(
                    f"Placed: broker_order_id={ack.broker_order_id} status={ack.status} "
                    f"(market orders queue outside RTH — check the Alpaca dashboard)"
                )
            )
