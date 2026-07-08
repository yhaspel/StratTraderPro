"""Seed the SMA-crossover demo system strategy (M09 §6.1).

Idempotent: upserts a system ``Strategy`` (``owner=NULL``, ``is_system=True``,
``slug="sma-cross-demo"``) matching the ``SmaCrossAdapter`` so the backtester is
demonstrable on a fresh install. Uses the existing ``upsert_system_strategy``
service so the row shape matches the M03 seed catalogue exactly.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.strategies.services import upsert_system_strategy

SLUG = "sma-cross-demo"

_PINE = b"""//@version=5
// SMA crossover demo strategy (backtestable via apps.backtest.strategies.sma_cross).
// Signals: long entry when fast SMA crosses above slow SMA; exit on the reverse.
strategy("SMA Cross Demo", overlay=true)
fast = ta.sma(close, input.int(10, "fast"))
slow = ta.sma(close, input.int(30, "slow"))
if ta.crossover(fast, slow)
    strategy.entry("long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("long")
"""

_DESC = b"""SMA Crossover (demo)

A long-only fast/slow simple-moving-average crossover. Shipped as the M09
walk-forward backtester demo: it has a registered in-repo Python adapter
(sma-cross-demo) so it can be backtested out of the box.
"""

_WEBHOOK = json.dumps(
    {
        "strategy": SLUG,
        "action": "buy",
        "symbol": "AAPL",
        "qty": 1,
        "order_type": "MKT",
        "sig": "PASTE_YOUR_SECRET_HERE",
        "idempotency_key": "tv-{{strategy.order.id}}-{{time}}",
    },
    indent=2,
).encode("utf-8")


class Command(BaseCommand):
    help = "Seed the SMA-crossover demo system strategy (idempotent)."

    def handle(self, *args, **options):
        strategy, changed = upsert_system_strategy(
            slug=SLUG,
            name="SMA Cross Demo",
            description_short="Long-only fast/slow SMA crossover — M09 backtester demo.",
            pine_filename="sma_cross_demo.pine",
            pine_bytes=_PINE,
            desc_filename="sma_cross_demo.md",
            desc_bytes=_DESC,
            webhook_filename="sma_cross_demo.json",
            webhook_bytes=_WEBHOOK,
        )
        verb = "created/updated" if changed else "unchanged"
        self.stdout.write(self.style.SUCCESS(f"Demo strategy '{strategy.slug}' {verb} (id={strategy.id})."))
