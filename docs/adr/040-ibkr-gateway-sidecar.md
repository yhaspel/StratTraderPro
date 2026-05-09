# ADR-040 — IB Gateway sidecar on Railway

**Date:** 2026-05-09
**Status:** Spike in progress (Day 1 of M04)
**Milestone:** M04 — Webhook Ingest + IBKR Paper

> This ADR is a **living document for the duration of the M04 Day-1 spike**.
> The Findings and Decision sections will be filled in once the smoke test
> has been run against a real IB Gateway sidecar on Railway. Once filled in,
> Status flips to Accepted (or Rejected, if the spike fails) and the next
> ADR (041) covers the actual production topology choice.

## Context

M04's plan §6.2 specifies running IB Gateway as a Railway sidecar with IBC
for headless auto-login and `ib_insync` connecting from the worker service.
Eight of M04's twelve ACs (AC-04-6 through 12, plus the §10.4 live test)
sit on top of this topology working. If the sidecar approach is unworkable
on Railway, we want to know on Day 1 — before the broker adapter, the
webhook endpoint, and the dashboard get written against assumptions that
don't hold.

This is a **spike** ADR: the artifacts it describes (`docker/ib-gateway/`,
`scripts/spike_ibkr_smoke.py`, the `ibkr-spike` compose profile) are
throwaway-or-promote. Either the spike validates the topology and we
promote the Dockerfile + entrypoint into M04's production path, or it
fails and this ADR documents the failure mode and the alternative we
pursue.

## The four assumptions to prove

| # | Assumption | How the spike tests it |
|---|---|---|
| A1 | IB Gateway boots headless on a Linux container via IBC, taking paper credentials from env vars, with no manual click. | `docker compose --profile ibkr-spike up -d ib-gateway` reaches HEALTHY (TCP 4002) within `start_period=180s`. |
| A2 | A separate process can connect to the Gateway via `ib_insync` on `localhost:4002` and exercise the API (account read, order place, fill capture). | `scripts/spike_ibkr_smoke.py` exits 0. |
| A3 | After a forced disconnect, the same `clientId` can re-bind without restarting the Gateway. | Smoke step 5: `ib.disconnect()`, sleep 3s, reconnect, expect success. |
| A4 | The credential injection model (env vars now, encrypted-creds-into-tmpfs in M04 proper) is feasible on Railway's networking + secrets model. | Discovery during deploy: do paper creds round-trip via Railway env vars without truncation? Does Railway support inter-service localhost or do we need an explicit private network? |

## The spike artifacts

```
docker/ib-gateway/
  Dockerfile           # eclipse-temurin:17-jre-jammy + Xvfb + IB Gateway + IBC
  entrypoint.sh        # renders config.ini, starts Xvfb, exec ibcstart.sh
  ibc-config.ini       # IBC config template; placeholders filled at boot

docker-compose.yml     # adds `ib-gateway` service under profile `ibkr-spike`

scripts/
  spike_ibkr_smoke.py  # ib_insync connect → account → order → fill → reconnect
  README.md            # explains the scripts/ folder convention

docs/runbooks/
  spike-ibkr-gateway.md  # step-by-step run instructions
```

### Topology under test

```
┌───────────────────────────┐           ┌────────────────────────┐
│  spike_ibkr_smoke.py      │  TCP      │  ib-gateway container  │
│  (host machine OR a       │  4002     │   ├─ Xvfb (:1)         │
│   sibling Railway svc)    │  ───────▶ │   ├─ IB Gateway (Java) │
│  ib_insync 0.9.86         │           │   └─ IBC (auto-login)  │
└───────────────────────────┘           └────────────────────────┘
                                              ▲
                                              │ TWS_USERID / TWS_PASSWORD
                                              │ via env (spike) → encrypted
                                              │ tmpfs (M04 proper, §6.2)
```

### Pinned versions (spike)

- IB Gateway: `stable-standalone` channel (whatever IBKR ships at build time)
- IBC: `3.20.0` (`ARG IBC_VERSION` in Dockerfile — bump if upstream URL 404s)
- Base: `eclipse-temurin:17-jre-jammy`
- `ib_insync`: `0.9.86`

A known fragility: IBKR's installer URLs change without notice. If the
build breaks because the URL 404s, the standard fix is to look at the
[gnzsnz/ib-gateway](https://github.com/gnzsnz/ib-gateway) image tags and
pin to whatever channel it's currently using.

## Findings

> **TO BE FILLED IN** after running the smoke test. Template:
>
> - **A1 (boot):** ⏳ pending / ✅ passed (cold start: __s) / ❌ failed (reason: __)
> - **A2 (connect + order):** ⏳ pending / ✅ passed (broker_order_id: __, fill_price: __) / ❌ failed
> - **A3 (reconnect):** ⏳ pending / ✅ passed / ❌ failed
> - **A4 (Railway env model):** ⏳ pending / ✅ passed / ❌ failed
>
> Notes (gotchas, surprises, things to write into M04 proper):
>
> -

## Decision

> **TO BE FILLED IN** based on Findings. Three possible outcomes:
>
> 1. **Promote** — All four assumptions hold. Promote `docker/ib-gateway/`
>    into M04 proper as the production sidecar; rewrite this ADR's Status
>    to "Accepted" and replace the Findings section with the production
>    topology detail.
> 2. **Promote with changes** — Some assumptions hold, others need a
>    different shape (e.g., we need a second Postgres-backed credentials
>    table instead of env, or we need to co-locate Gateway with worker
>    rather than running it as a separate Railway service). Document the
>    shape change here, then proceed.
> 3. **Reject** — The Railway sidecar topology is unworkable. Pivot
>    options to evaluate before committing to one:
>    - Run IB Gateway on a small DigitalOcean / Hetzner VPS outside Railway,
>      tunnel TCP 4002 over Tailscale or a Wireguard mesh.
>    - Drop IBKR for M04 and start with TradeStation (M05's broker — REST
>      API, no Gateway needed) so the milestone unblocks while we figure
>      IBKR out separately.
>    - Use IBKR's REST `Client Portal API` instead of the TWS API; trades
>      latency and feature set for not needing a Gateway at all.

## Consequences

> **TO BE FILLED IN** with whatever the Decision is.

## Out of scope for this spike (deferred to M04 proper)

- Per-user Gateway pool with Redis-locked routing (plan §6.2 design).
- Encrypted credentials at rest (KEK-wrapped DEK per user).
- `BROKER_IBKR_ENABLED` feature flag wiring.
- Prometheus metrics emission (`broker_connect_total`, `broker_disconnects_total`).
- 2FA / nightly reauth handling for live mode (M13+ — paper avoids this).
- Production HEALTHCHECK tuning + restart policy.
- VNC removed; debug surface gated by env only.

## See also

- `project-plan/04-webhook-ingest-and-ibkr.md` §6.2 — production design
- `docs/runbooks/spike-ibkr-gateway.md` — how to run the smoke test
- `scripts/spike_ibkr_smoke.py` — the smoke test itself
- ADR-002 — Railway hosting (the platform constraints we're testing against)
