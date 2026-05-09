# docker/ib-gateway/

**Status:** SPIKE — see `docs/adr/040-ibkr-gateway-sidecar.md`.

Throwaway-or-promote IB Gateway sidecar for the M04 Day-1 spike. Builds an
image that runs IB Gateway headless via IBC against an IBKR paper account.

To run, follow `docs/runbooks/spike-ibkr-gateway.md`.

## Files

| File | What |
|---|---|
| `Dockerfile` | `eclipse-temurin:17-jre-jammy` + Xvfb + IB Gateway + IBC |
| `entrypoint.sh` | Renders IBC config.ini from env, boots Xvfb, exec's IBC |
| `ibc-config.ini` | IBC config template; `__TWS_USERID__`, `__TWS_PASSWORD__`, `__TRADING_MODE__` substituted at boot |

## When this folder becomes obsolete

When the ADR flips to **Rejected**: delete this folder and the `ib-gateway`
service from `docker-compose.yml`.

When the ADR flips to **Accepted**: promote into M04 proper. Likely
restructuring: split per-user vs. shared bits, replace env-based credential
injection with a Django-rendered config tied to encrypted DB rows, harden
the HEALTHCHECK and add Prometheus exposition.
