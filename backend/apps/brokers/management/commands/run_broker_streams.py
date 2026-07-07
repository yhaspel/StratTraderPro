"""run_broker_streams — always-on fill-streams service (M04 §6.5).

Deployed as its own lightweight Railway service (mirrors worker/beat). Locally
a docker-compose `streams` service. One TradingStream thread per connected
paper account; heartbeats power the /status/ endpoint; supervised restart with
backoff + REST catch-up on reconnect.
"""
from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.brokers.streams import StreamSupervisor


class Command(BaseCommand):
    help = "Run the broker fill-streams supervisor (one TradingStream per account)."

    def add_arguments(self, parser):
        parser.add_argument("--heartbeat-interval", type=float, default=15.0)

    def handle(self, *args, **options):
        if not getattr(settings, "BROKER_ALPACA_ENABLED", True):
            self.stdout.write(self.style.WARNING("BROKER_ALPACA_ENABLED is off — exiting cleanly."))
            return
        self.stdout.write(self.style.SUCCESS("Starting broker streams supervisor…"))
        supervisor = StreamSupervisor(heartbeat_interval=options["heartbeat_interval"])
        supervisor.run_forever()
