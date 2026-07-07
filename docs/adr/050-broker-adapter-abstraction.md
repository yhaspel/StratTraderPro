# ADR-050 — The `BrokerAdapter` abstraction, proven by a second implementation

**Date:** 2026-07-07
**Status:** Accepted
**Milestone:** M05 — TradeStation + Order Lifecycle
**Reference:** `project-plan/05-tradestation-and-order-lifecycle.md` §6.1, §6.2, §11;
ADR-041 (the IBKR→Alpaca pivot this seam absorbed)

## Context

M04 shipped a single `BrokerAdapter` protocol (`backend/apps/brokers/base.py`)
with one real implementation — `AlpacaAdapter` — plus a `FakeBrokerAdapter` for
tests. The bet, stated in ADR-041, was that "the `BrokerAdapter` protocol is
unchanged — this pivot swaps the first concrete implementation, exactly the swap
M04A was designed to prove cheap. TradeStation (M05) slots in unchanged later."

M05's job is to cash that bet: add a **second** production broker
(`TradeStationPaperAdapter`) behind the **same** contract and confirm nothing
above the adapter line — the webhook→order pipeline, reconciliation, the Orders
page, broker routing — has to learn what broker it is talking to. This ADR
records the shape of the abstraction as it now stands with two real
implementations behind it, and what the second one taught us.

> **Descope (honest status).** TradeStation API access is approval-gated and
> was not granted in the M05 window (the exact failure mode ADR-041 called out
> and the plan's 2026-07-05 review note pre-planned for). So the TradeStation
> adapter, its thin `httpx` client, and the OAuth2/PKCE code path ship **behind
> `BROKER_TRADESTATION_ENABLED=false`**, exercised by unit tests against the
> documented wire formats and recorded fixtures — **not** by a live handshake or
> real sim fills. The *live* OAuth consent + real sim fills are **deferred**
> until access is granted. The broker-agnostic order-lifecycle half (extended
> order types, unified `OrderRequest`, asset classes, reconciliation, Orders
> page/CSV, broker routing, live-mode rejection) is **fully built and tested**.
> Crucially, the abstraction itself is proven regardless: a second
> implementation exists, satisfies the protocol at import time
> (`@runtime_checkable`), and is unit-tested end to end against TradeStation's
> documented API shapes. What is unproven is TradeStation's live behavior, not
> our seam.

## Decision

### 1. The protocol is a small, synchronous, vendor-free surface

`BrokerAdapter` is a `typing.Protocol` (`runtime_checkable`) with two class
attributes and nine methods:

```python
name: str
supported_asset_classes: list[str]

connect()            -> ConnectionInfo
disconnect()         -> None
get_account()        -> Account
list_positions()     -> list[PositionDTO]
list_open_orders()   -> list[OrderAck]
place_order(req, client_order_id) -> OrderAck
cancel_order(broker_order_id)     -> None
flatten_all(reason)  -> list[OrderAck]
health()             -> BrokerHealth
```

Two design rules carried from M04 held up under the second implementation and
are worth restating because they are what kept the seam clean:

- **`connect()` takes no credentials.** An adapter is constructed *per*
  `BrokerAccount` by the factory `brokers.services.build_adapter(account)` and
  decrypts its own secrets internally. Plaintext keys and tokens never travel
  through a call site. Alpaca decrypts an API-key pair; TradeStation decrypts
  OAuth tokens — the caller cannot tell the difference and never holds either.
- **Streaming is not on the protocol.** Fills are owned by the
  `run_broker_streams` service, which normalizes each broker's `trade_updates`
  feed into a `FillEvent` and writes it to a per-user Redis Stream. Adapters
  stay synchronous request/response. Adding TradeStation's WebSocket order-event
  stream therefore did not touch the protocol at all — it added a normalizer
  (`tradestation.mapping.from_ts_order_event`) alongside Alpaca's.

Everything above the adapter speaks the DTOs below, never a vendor SDK type.

### 2. The DTOs — one `OrderRequest`, extended for M05 asset classes

The unified request (`base.OrderRequest`, a frozen dataclass) is what the
webhook pipeline builds once and hands to whichever adapter routing selected:

```python
@dataclass(frozen=True)
class OrderRequest:
    symbol: str                       # canonical (see §4)
    side: Side                        # BUY | SELL  (open/close variants live on
                                      #   the persisted Order model, below)
    qty: Decimal
    order_type: OrderType   = MKT     # MKT | LMT | STP | STP_LMT
    limit_price: Decimal | None = None
    stop_price:  Decimal | None = None
    time_in_force: TimeInForce = DAY  # DAY | GTC | IOC
    asset_class: str = "STOCK"        # STOCK | ETF | OPTION | FUTURE
    option: OptionContract | None = None   # expiry, strike, right (CALL|PUT)
    future: FutureContract | None = None   # root, expiry (YYYY-MM)
```

`client_order_id` is passed **separately** to `place_order` rather than living
on the request, so the idempotency anchor is explicit at the one call that
places the order. The persisted `orders.Order` model carries the fuller side
enum (`BUY_TO_OPEN`/`SELL_TO_OPEN`/`BUY_TO_CLOSE`/`SELL_TO_CLOSE` for options)
plus the flattened descriptor columns (`option_expiry`, `option_strike`,
`option_right`, `future_root`, `future_expiry`); each adapter's payload builder
collapses the open/close side variants to whatever that broker understands.

Supporting DTOs — all frozen dataclasses in `base.py`: `ConnectionInfo`,
`Account`, `PositionDTO`, `OptionContract`, `FutureContract`, `OrderAck`,
`FillEvent`, `BrokerHealth`, and the `Side`/`OrderType`/`TimeInForce`/
`AssetClass`/`OrderStatus`/`BrokerConnState` enums.

### 3. Per-adapter `to_broker_payload` / `from_broker_ack` mapping

Each adapter owns a `mapping.py` that realizes the plan's abstract pair — build
the vendor payload from an `OrderRequest`, parse the vendor ack/order back into
an `OrderAck` (and the stream event into a `FillEvent`). The names differ per
module but the contract is identical:

| Direction | Alpaca (`alpaca/mapping.py`) | TradeStation (`tradestation/mapping.py`) |
|---|---|---|
| `OrderRequest` → payload | `build_order_request` (returns an `alpaca-py` `*OrderRequest`) | `to_ts_order_payload` (returns the TS v3 order dict) |
| ack/order → `OrderAck` | `map_order_ack` | `from_ts_order` |
| account → `Account` | `map_account` | `from_ts_account` |
| position → `PositionDTO` | `map_position` | `from_ts_position` |
| stream event → `FillEvent` | `map_trade_update` | `from_ts_order_event` |

Order-type and status vocabularies are per-adapter lookup tables, so a new
broker is a table plus a symbol converter — not a new branch in the pipeline.
Alpaca uses the SDK's typed request models (`MarketOrderRequest`,
`LimitOrderRequest`, `StopOrderRequest`, `StopLimitOrderRequest`); TradeStation
maps to string `OrderType` values `Market`/`Limit`/`StopMarket`/`StopLimit` and
a nested `TimeInForce.Duration`.

### 4. Canonical symbology, and each broker's conversion

The pipeline stores and reasons in **one canonical form**; each adapter
converts at the edge:

- **Stocks / ETFs** — the bare ticker, unchanged on both brokers
  (`AAPL`, `SPY`, `BRK.B`).
- **Options** — canonical is the **OCC/OPRA** symbol
  `AAPL240119C00150000` (root + `YYMMDD` + `C`/`P` + 8-digit strike in
  thousandths).
  - **Alpaca** takes the OCC symbol **as-is** — options are placed by their OCC
    string. Alpaca's `supported_asset_classes` is `STOCK`/`ETF`/`OPTION`.
  - **TradeStation** wants its own spaced form:
    `AAPL240119C00150000` → **`AAPL 240119C150`** (a space after the root, and
    the strike with the three trailing implied-decimal zeros trimmed). Done by
    `tradestation.mapping.to_ts_symbol`.
- **Futures** — canonical is **root + `YYYY-MM`** (e.g. `ES` + `2026-12`).
  - **Alpaca has no futures.** A `FUTURE` `OrderRequest` is rejected in
    `AlpacaAdapter.place_order` with `ORDER_UNSUPPORTED_ASSET`
    (`BrokerErrorCode.UNSUPPORTED_ASSET`) before any network call —
    `FUTURE` is simply absent from Alpaca's `_SUPPORTED_ASSET_CLASSES`.
  - **TradeStation** converts to the **month-code** form
    `ES` + `2026-12` → **`ESZ26`** (root + CME month code + 2-digit year).

  **CME contract-month codes** (the table `to_ts_symbol` uses):

  | Month | Code | Month | Code | Month | Code |
  |---|---|---|---|---|---|
  | Jan (01) | **F** | May (05) | **K** | Sep (09) | **U** |
  | Feb (02) | **G** | Jun (06) | **M** | Oct (10) | **V** |
  | Mar (03) | **H** | Jul (07) | **N** | Nov (11) | **X** |
  | Apr (04) | **J** | Aug (08) | **Q** | Dec (12) | **Z** |

  So `ES 2026-03 → ESH26`, `NQ 2026-06 → NQM26`, `ES 2026-12 → ESZ26`. A leading
  `@` on the canonical root is stripped before conversion.

Keeping the *canonical* form OCC-for-options and `root + YYYY-MM`-for-futures
means the webhook contract, the `Order` rows, reconciliation keys, and the CSV
export are all broker-independent — only the two `mapping.py` files know a
vendor's spelling.

### 5. Credentials are per-adapter, both Fernet-wrapped with the platform KEK

The abstraction hides two *different* credential models behind the same
`build_adapter(account)` factory and the same at-rest envelope:

- **Alpaca** — an **API key ID + secret pair**, stored on
  `BrokerAccount.api_key_id_enc` / `api_secret_enc` (Fernet-wrapped `BinaryField`s).
  User pastes them once; write-only at the serializer.
- **TradeStation** — **OAuth2 access + refresh tokens**, stored on
  `BrokerAccount.ts_access_token_enc` / `ts_refresh_token_enc`
  (Fernet-wrapped), plus `ts_expires_at` and `ts_scope`. Populated by the OAuth
  callback, not by the user typing anything.

Both use the **same** platform KEK as MFA and webhook secrets (ADR-031), so KEK
rotation (`docs/runbooks/mfa-kek-rotation.md`) re-wraps every broker credential
in one operation regardless of broker. The `BrokerContext`/adapter never logs a
key or token — `__repr__` on the credential-carrying structs is a redaction
guard.

### 6. Why the abstraction earned its keep — twice

- **The IBKR→Alpaca pivot (ADR-041) touched zero call sites above the seam.**
  It swapped the first concrete implementation. That pivot is the reason M04
  shipped at all after two IBKR paths died on approval/operational walls.
- **Adding TradeStation touched zero call sites either.** The whole second
  broker is: one adapter class, one `mapping.py` (symbology + payload/ack), one
  thin `httpx` client, an OAuth module, and two DB columns. Routing, order
  persistence, reconciliation, the Orders page, and the CSV export required
  **no** broker-specific branches — they consume `OrderRequest`/`OrderAck`/
  `PositionDTO`/`FillEvent`, which are identical for both. The parity test suite
  parameterizes `[ALPACA, TRADESTATION]` over the same cases.

That is the whole thesis: the cost of a new broker is confined to a corner of
`apps/brokers/<vendor>/`, and everything downstream is written once.

## Consequences

**Positive:**

- A third broker is a bounded, well-mapped task: a `mapping.py`, an adapter, a
  credential model, a client. No pipeline surgery.
- Canonical symbology documented here (options OCC, futures `root + YYYY-MM`)
  is the single source of truth; the two vendor spellings are derived, tested
  conversions — not scattered string-munging.
- Credential heterogeneity (key-pair vs OAuth) is invisible above the factory
  and covered by one KEK-rotation runbook.

**Negative / honest limits:**

- **TradeStation is proven against its *documented* API, not its *live* one.**
  Recorded fixtures and unit tests can encode a wrong assumption about TS's real
  wire shapes (this is the ADR §16 "adapter symbology mismatch" risk, rated
  Med/High). The symbology conversions here are the highest-risk surface and are
  the first thing to re-validate when access is granted.
- The protocol is deliberately synchronous; a broker with a fundamentally
  push-only order model would need the streams service to carry more, not the
  protocol. Acceptable — both current brokers fit request/response for placement.
- `to_broker_payload`/`from_broker_ack` are a *convention* realized as
  differently-named module functions per adapter, not a single enforced method
  on the protocol. The parity suite is what keeps them honest.

## Alternatives considered

1. **Put `to_broker_payload`/`from_broker_ack` on the protocol as methods.**
   Rejected: mapping is pure and testable as free functions; forcing it onto the
   protocol adds ceremony without removing the real coupling (the vendor
   vocabulary tables), which has to live somewhere per-adapter anyway.
2. **A canonical symbology that mirrors one broker (e.g. store TS futures
   codes).** Rejected: it privileges one vendor and pushes conversion cost onto
   the *other* adapter and onto every downstream reader. OCC + `root + YYYY-MM`
   are vendor-neutral and human-legible.
3. **Ship TradeStation "dark" with no code until access lands.** Rejected: the
   milestone's entire point is to *prove the seam*. Building the adapter behind a
   flag, fully unit-tested, proves the abstraction now and leaves only live
   verification for later — which is exactly the descope we took.

## See also

- ADR-041 — Alpaca replaces IBKR (the first swap this seam absorbed)
- ADR-051 — Reconciliation policy (a downstream consumer of `list_positions()`)
- `docs/runbooks/tradestation-oauth-recover.md` — operating the TS OAuth path
- `backend/apps/brokers/base.py` — the protocol + DTOs
- `backend/apps/brokers/alpaca/mapping.py`, `backend/apps/brokers/tradestation/mapping.py`
- `backend/apps/brokers/services.py::build_adapter` — the per-account factory
- `project-plan/05-tradestation-and-order-lifecycle.md` §6.1, §6.2
