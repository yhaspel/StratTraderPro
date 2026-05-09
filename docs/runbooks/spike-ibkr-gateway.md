# Runbook — M04 Day-1 spike: IB Gateway sidecar smoke test

**Owner:** Yuval
**Lifecycle:** Spike-only. Once `docs/adr/040-ibkr-gateway-sidecar.md`
flips to Accepted/Rejected, this runbook is either superseded by
`docs/runbooks/ib-gateway-reauth.md` (M04 production runbook) or deleted.

## What this proves

The four assumptions enumerated in ADR-040. See that ADR for context.

## Prerequisites

### IBKR account in paper-trading mode

Two paths depending on what you already have:

**Path A — Standalone paper account (free demo).** If you don't have a
live IBKR account, create a free demo at
<https://www.interactivebrokers.com/en/trading/free-demo.php>. You get a
distinct username (often `edemoXXXXX` or similar) that only logs into
paper. Use those credentials for `TWS_USERID` / `TWS_PASSWORD`.

**Path B — Unified live account with paper toggle (most current accounts,
including all IBKR Israel / IB Ireland accounts).** You have a single
username/password that logs into either Live or Paper based on a toggle
on the web login screen. For headless use:

- Put your **live** username/password into `TWS_USERID` / `TWS_PASSWORD`.
- The `TradingMode=paper` line in `ibc-config.ini` (rendered by the
  entrypoint) is the headless equivalent of that web-login toggle. IB
  Gateway authenticates against your live identity but binds the session
  to the paper sub-account (the `DU…` account ID, not the `U…`).
- The smoke test will see only the `DU…` account in `accountSummary()` —
  this is correct.

> **Critical for Path B: disable 2FA for paper sessions.**
> If your account uses Secure Login System (IB Key push, SMS, hardware
> card), the headless login will hang on a push approval that IBC can't
> auto-confirm and time out after ~3 min. IBKR lets you keep 2FA on for
> live and off for paper:
>
> 1. Log into <https://www.interactivebrokers.com/sso/Login>.
> 2. Settings → User Settings → Security → **Secure Login System**.
> 3. Find the toggle named something like "Use Secure Login System for
>    Paper Trading" / "Require Two-Factor for Paper Trading" (the exact
>    label varies by IBKR entity). Turn it **off**. Save.
> 4. Wait ~5 min for the change to propagate.
>
> If the toggle isn't visible in your portal, open a chat with IBKR
> support and ask them to "exempt paper trading from Secure Login System
> for headless API access" — they handle this routinely.

Before the first container build, **manually log into paper mode via the
IBKR web client at least once** — proves credentials + paper enablement
work end-to-end before IBC and Docker enter the failure space.

### Local tooling

- **Docker Desktop** running locally (Apple Silicon is fine — the base
  image is multi-arch via `eclipse-temurin`).
- **Python 3.12+** with `pip` for the smoke test.

## Set up local credentials

Add the paper credentials to the project-root `.env` (gitignored):

```bash
# .env
TWS_USERID=your_paper_username
TWS_PASSWORD=your_paper_password
# Optional — exposes a no-password VNC on localhost:5900 so you can watch
# the IB Gateway window in real time. Only enable when debugging the spike.
DEBUG_VNC=0
```

The compose service reads these via `${TWS_USERID:-}` / `${TWS_PASSWORD:-}`
substitution, so the file must be at the repo root (where `docker-compose.yml`
lives), not inside `backend/`.

## Run

### 1. Build + start the sidecar

```bash
docker compose --profile ibkr-spike build ib-gateway
docker compose --profile ibkr-spike up -d ib-gateway
```

The build pulls the IB Gateway installer from IBKR's CDN. If the build
fails with a 404 on the installer URL, see ADR-040 § "Pinned versions"
for the bump procedure.

### 2. Watch it boot

```bash
docker compose logs -f ib-gateway
```

Expect to see, in order:

1. `[entrypoint] rendering IBC config.ini`
2. `[entrypoint] starting Xvfb on :1`
3. `[entrypoint] Xvfb is up`
4. `[entrypoint] detected IB Gateway version: <number>`
5. `[entrypoint] starting IBC (mode=paper, port=4002)`
6. IBC's own log: `Login completed`
7. (silence — Gateway is now serving the API)

Cold start is typically 60–120s. The Docker `HEALTHCHECK` has a 180s
`start_period` so the container won't be marked unhealthy during boot.

Verify the API port is open from the host:

```bash
nc -zv localhost 4002    # should print "Connection succeeded"
```

If `DEBUG_VNC=1`, point a VNC client (macOS: `open vnc://localhost:5900`)
at the container — you'll see the IB Gateway window with the API status
in the bottom-right.

### 3. Run the smoke test

```bash
pip install ib_insync==0.9.86
python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id 7
```

### 4. Read the output

The script prints a summary block at the end. Copy it verbatim into
ADR-040's **Findings** section. Example (real numbers will differ):

```
============================================================
SPIKE RESULT — copy this into the ADR's Findings section
============================================================
  cold_start_seconds        = 4.2
  connect_ok                = True
  account_summary_keys      = 47
  broker_order_id           = 1
  order_status_after_place  = Filled
  fill_count                = 1
  fill_price                = 211.34
  reconnect_ok              = True
============================================================
ALL STEPS PASSED — assumptions 1-3 proven for this topology.
```

Note `cold_start_seconds` here is the time `ib_insync.connect` took, not
the container's full boot time. For container boot, watch the timestamp
delta between `docker compose up -d` and the `Login completed` log line.

## Failure-mode triage

The smoke test exits with a category-specific code. Look up here, then
write the diagnosis into ADR-040's Findings.

| Exit | Step | What to check first |
|------|------|---------------------|
| 1 | connect | `docker compose ps ib-gateway` — is it healthy? `docker logs` for IBC errors. Confirm port 4002 is listening: `docker compose exec ib-gateway nc -z localhost 4002`. **For Path B accounts:** if `docker logs` shows IBC stalled at "Logging in" for 2+ minutes, this is almost certainly the 2FA hang — go disable Secure Login System for paper trading (see Prerequisites) and rebuild. |
| 2 | account read | Login worked (got past 1) but the API has no entitlements. Usually means the account isn't fully provisioned yet — paper accounts created in the last hour can be in this state. Wait 15 min and retry. |
| 3 | place_order | Common cause: `Stock` contract not qualified (symbol typo, exchange wrong). Re-check the script's contract definition. Less common: account has no buying power — check the Account Summary output from step 2. |
| 4 | no fill | Outside US Regular Trading Hours (09:30–16:00 ET). Order is sitting in `PreSubmitted`. Rerun during RTH; this is not a topology failure. |
| 5 | reconnect | Gateway didn't release the prior client ID on disconnect. Try a different `--client-id`; if that works, document the workaround for the broker adapter (it'll need to rotate IDs). If even a fresh ID fails, the Gateway crashed on disconnect — that's a real assumption-3 failure. |

## Run it on Railway (the actual platform test)

Local Docker proves A1–A3 with Mac networking. Railway is the platform
we actually need this to work on, so the spike isn't done until it
passes there too:

1. Create a new Railway service from the same Dockerfile (`docker/ib-gateway/Dockerfile`).
   Service type: Worker (no public domain — we don't want 4002 reachable
   from the internet).
2. Set `TWS_USERID` and `TWS_PASSWORD` as Railway env vars on that service.
3. Note Railway's **internal** hostname for the service (something like
   `ib-gateway.railway.internal`).
4. Run the smoke test from a sibling Railway service (or temporarily SSH
   into one), pointing `--host` at the internal hostname:
   ```bash
   python scripts/spike_ibkr_smoke.py --host ib-gateway.railway.internal --port 4002
   ```
5. If A1–A3 pass on Railway, A4 is also proven.

## Tear down

```bash
docker compose --profile ibkr-spike down
```

If you want to keep the image around for the next iteration:

```bash
docker compose --profile ibkr-spike stop ib-gateway
```

## When this runbook becomes obsolete

When ADR-040 flips to **Accepted**: rename to `docs/runbooks/ib-gateway-reauth.md`
(per M04 plan §14) and rewrite for the production topology — per-user
sessions, encrypted creds, Railway-native deploy. The smoke script can
either be promoted into a Django management command or deleted depending
on what we end up needing for ongoing health checks.

When ADR-040 flips to **Rejected**: delete this file along with
`docker/ib-gateway/`, `scripts/spike_ibkr_smoke.py`, and the `ib-gateway`
compose service. The ADR stays — we want a record of why the topology
didn't work.
