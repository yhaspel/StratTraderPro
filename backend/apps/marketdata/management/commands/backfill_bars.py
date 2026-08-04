"""backfill_bars — historical daily-bar backfill from FMP (M06 §5 DoD).

    python manage.py backfill_bars --symbols SPY,QQQ,IWM --from 2015-01-01

Requires an FMP key (a deferred external) — UI-stored (Settings → Data
Providers) or the FMP_API_KEY env var (ADR-062). Idempotent — safe to re-run
(upserts on (symbol, tf, ts)); re-running does not duplicate bars (AC-06-1).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.marketdata.fmp import FMPClient
from apps.marketdata.metrics import MARKETDATA_BARS_INGESTED
from apps.marketdata.services import upsert_bars


class Command(BaseCommand):
    help = "Backfill daily bars from FMP for the given symbols."

    def add_arguments(self, parser):
        parser.add_argument("--symbols", required=True, help="Comma-separated symbols.")
        parser.add_argument("--from", dest="from_date", default=None)
        parser.add_argument("--to", dest="to_date", default=None)

    def handle(self, *args, **options):
        from apps.marketdata.keys import resolve_key

        if not resolve_key("FMP"):
            raise CommandError(
                "No FMP key is configured. Set one in Settings → Data Providers "
                "(staff) or via the FMP_API_KEY env var (.env / Railway)."
            )
        symbols = [s.strip().upper() for s in options["symbols"].split(",") if s.strip()]
        client = FMPClient()
        total = 0
        for sym in symbols:
            rows = client.daily_bars(sym)
            if options["from_date"]:
                rows = [r for r in rows if str(r["ts"]) >= options["from_date"]]
            if options["to_date"]:
                rows = [r for r in rows if str(r["ts"]) <= options["to_date"]]
            result = upsert_bars(sym, "1d", rows)
            MARKETDATA_BARS_INGESTED.labels(tf="1d").inc(result["created"])
            total += result["created"]
            self.stdout.write(
                self.style.SUCCESS(f"{sym}: +{result['created']} new, {result['updated']} unchanged")
            )
        self.stdout.write(self.style.SUCCESS(f"Backfill complete: {total} new bars."))
