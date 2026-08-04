"""Default RiskProfile provisioning (P0-1).

A user with no ``RiskProfile`` has the entire sizing + daily-loss layer disabled:
no position/leverage clamp, no asset-class filter, no L2 auto-halt. Provisioning a
conservative profile on broker connect makes the common case safe-by-default
rather than reject-by-default (live) / unsized (paper). Idempotent — never
overwrites a profile the user has already tuned.
"""
from __future__ import annotations

from decimal import Decimal

from .models import RiskProfile

# Strictly conservative starting point (plan P0-1). The user can loosen these in
# the risk UI; the point is that "connected but never configured" is still safe.
_DEFAULTS = dict(
    risk_per_trade_pct=Decimal("0.5"),
    max_position_pct=Decimal("10"),
    max_concurrent=3,
    daily_loss_usd=Decimal("1000"),
    daily_loss_pct=Decimal("3"),
    leverage_cap=Decimal("1"),
    soft_stop_pct=Decimal("5"),
    hard_stop_pct=Decimal("10"),
    strict_mode=True,
)


def ensure_default_risk_profile(user) -> RiskProfile:
    """Create a conservative default profile for ``user`` if none exists."""
    profile, _created = RiskProfile.objects.get_or_create(
        user=user,
        defaults={**_DEFAULTS, "permitted_asset_classes": RiskProfile.default_permitted()},
    )
    return profile
