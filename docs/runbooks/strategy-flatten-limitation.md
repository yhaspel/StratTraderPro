# Runbook — STRATEGY-scope kill switch cannot flatten (FIX-H4)

**Last reviewed:** 2026-07-12

**Status:** current limitation (M08). Removal tracked for M09.

## What
A kill switch created with `scope=STRATEGY` and `flatten=true` is **rejected**
at the API (`FLATTEN_SCOPE_UNSUPPORTED`, HTTP 400). Only `USER` and `PLATFORM`
scope may flatten.

## Why
Positions carry no `strategy_id` — the platform records `orders.Position` per
`(broker_account, symbol)`, not per originating strategy. `flatten_user()` loops
the user's accounts and calls the broker's `flatten_all` (Alpaca
`close_all_positions`), which liquidates the **entire account**. A STRATEGY-scope
flatten therefore could not be scoped to the strategy's positions and would flat
the whole account — silently doing far more than the operator asked.

The safe behaviour: the L0 strategy toggle still **halts new orders** for that
strategy (`is_blocked → STRATEGY_HALTED`); it just cannot auto-liquidate.

## Operator action to flatten a single strategy today
1. Toggle the STRATEGY kill switch **without** flatten (halts new orders).
2. Manually close that strategy's positions in the broker (or use a USER-scope
   flatten if flatting the whole account is acceptable).

## Fix (M09)
Tag `orders.Position` (and `Order`) with the originating `strategy_id`, then
have `flatten_user(strategy_id=…)` place scoped close orders for only those
positions. Remove the serializer guard in `apps/risk/serializers.py`
(`KillSwitchCreateSerializer.validate`) once positions are tagged.
