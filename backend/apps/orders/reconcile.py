"""Position reconciliation (M05 §6.3).

Compares our persisted ``Position`` rows to the broker's authoritative list.
On the FIRST drift for a symbol we only record a ``ReconEvent(DRIFT)``; on the
SECOND consecutive drift we heal toward broker truth (update our Position —
never place corrective orders) and resolve the open drifts. A drift that
disappears on its own is resolved without healing.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.brokers.metrics import RECONCILE_DRIFTS_TOTAL, RECONCILE_HEALS_TOTAL
from apps.dashboard.events import POSITION_UPDATED, push_to_user

from .models import Position, ReconEvent

logger = logging.getLogger(__name__)

_TOLERANCE = Decimal("0.01")


def _open_drift(account, symbol):
    return (
        ReconEvent.objects.filter(
            broker_account=account, symbol=symbol,
            kind=ReconEvent.Kind.DRIFT, resolved_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )


def reconcile_account(account) -> list[ReconEvent]:
    """Reconcile one BrokerAccount. Returns the ReconEvents created this run.

    The broker fetch (network) happens OUTSIDE the DB transaction so a slow
    broker round-trip doesn't hold a Postgres connection open."""
    from apps.brokers.services import build_adapter

    adapter = build_adapter(account)
    broker_positions = {p.symbol: p for p in adapter.list_positions()}
    return _apply_reconcile(account, broker_positions)


@transaction.atomic
def _apply_reconcile(account, broker_positions) -> list[ReconEvent]:
    our_positions = {
        p.symbol: p for p in Position.objects.select_for_update().filter(broker_account=account)
    }
    events: list[ReconEvent] = []
    broker_label = str(account.broker).lower()

    for symbol in set(broker_positions) | set(our_positions):
        bq = broker_positions[symbol].qty if symbol in broker_positions else Decimal("0")
        oq = our_positions[symbol].qty if symbol in our_positions else Decimal("0")

        if abs(bq - oq) <= _TOLERANCE:
            # In sync — resolve any lingering open drift.
            ReconEvent.objects.filter(
                broker_account=account, symbol=symbol,
                kind=ReconEvent.Kind.DRIFT, resolved_at__isnull=True,
            ).update(resolved_at=timezone.now())
            continue

        prior = _open_drift(account, symbol)
        drift = ReconEvent.objects.create(
            user=account.user, broker_account=account, symbol=symbol,
            kind=ReconEvent.Kind.DRIFT, our_qty=oq, broker_qty=bq,
            detail=f"ours={oq} broker={bq}",
        )
        events.append(drift)
        RECONCILE_DRIFTS_TOTAL.labels(broker=broker_label, kind="position").inc()

        if prior is not None:
            # Second consecutive drift → heal toward broker truth.
            _heal(account, symbol, broker_positions.get(symbol))
            heal = ReconEvent.objects.create(
                user=account.user, broker_account=account, symbol=symbol,
                kind=ReconEvent.Kind.HEAL, our_qty=oq, broker_qty=bq,
                detail="healed toward broker", resolved_at=timezone.now(),
            )
            events.append(heal)
            RECONCILE_HEALS_TOTAL.inc()
            ReconEvent.objects.filter(
                broker_account=account, symbol=symbol,
                kind=ReconEvent.Kind.DRIFT, resolved_at__isnull=True,
            ).update(resolved_at=timezone.now())
    return events


def _heal(account, symbol, broker_pos):
    """Snap our Position to the broker. Never places corrective orders."""
    if broker_pos is None or broker_pos.qty == 0:
        Position.objects.filter(broker_account=account, symbol=symbol).update(
            qty=Decimal("0"), avg_cost=Decimal("0")
        )
    else:
        Position.objects.update_or_create(
            broker_account=account, symbol=symbol,
            defaults={
                "user": account.user,
                "qty": broker_pos.qty,
                "avg_cost": broker_pos.avg_cost,
                "market_price": broker_pos.market_price,
            },
        )
    pos = Position.objects.filter(broker_account=account, symbol=symbol).first()
    if pos is not None:
        from .services import position_to_wire

        push_to_user(account.user_id, POSITION_UPDATED, position_to_wire(pos))
