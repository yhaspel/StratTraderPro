"""M13 — the single source of truth for "is live trading permitted right now?".

Import this. Never read ``settings.ENABLE_LIVE_TRADING`` directly, and never call
``is_enabled("ENABLE_LIVE_TRADING")`` directly either. Both are half of the answer,
and the first draft of M13 shipped with exactly that bug.

WHY THIS FILE EXISTS
--------------------
``ENABLE_LIVE_TRADING`` is registered ``mutable=True, dangerous=True``, so
``admin_portal.flags.is_enabled()`` resolves a **database override first** and only
falls back to the env default. That gives two ways to read the flag, and reading
only one of them is wrong in both directions:

* Read only ``settings`` → an operator who flips the flag **OFF** in the admin
  portal (the documented emergency control) does not stop the adapter, which keeps
  trading real money. The off-switch reports success and does nothing — the exact
  shape of BUG-011.
* Read only ``is_enabled()`` → a **database write alone** could turn live trading
  **ON**, with no deploy, no code review, and no env change. A compromised or
  careless admin session becomes a real-money incident.

THE ASYMMETRY (the actual design decision)
------------------------------------------
A dangerous flag must be **hard to enable and trivial to disable**. So the
effective gate is an AND:

    env (settings.ENABLE_LIVE_TRADING)   must be True  → deliberate, deployed,
                                                          reviewed, auditable
    AND
    flag (is_enabled(...) DB override)   must be True  → operator can revoke
                                                          INSTANTLY, no redeploy

Consequences, both intended:
  * DB override OFF, env ON  → live trading STOPS immediately. Kill switch works.
  * DB override ON,  env OFF → live trading stays OFF. The DB cannot arm it.
"""
from __future__ import annotations

from django.conf import settings

FLAG = "ENABLE_LIVE_TRADING"


def live_trading_permitted() -> bool:
    """Effective live-trading gate. Call-time only — never cache this."""
    # Env is the arming pin: without it, nothing else matters.
    if not bool(getattr(settings, FLAG, False)):
        return False

    # The DB override is the trigger guard: it can only ever take permission AWAY.
    from apps.admin_portal.flags import is_enabled

    return bool(is_enabled(FLAG))
