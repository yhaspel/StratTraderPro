# docker/ib-gateway/

IB Gateway sidecar for M04. Runs IB Gateway headless via IBC against an
IBKR paper account, exposing the API on `localhost:4002` for the broker
adapter to consume.

See `docs/adr/040-ibkr-gateway-sidecar.md` for the topology rationale and
`docs/runbooks/ib-gateway-reauth.md` for operational procedures.

## Files

| File | What |
|---|---|
| `Dockerfile` | Thin wrapper over `gnzsnz/ib-gateway` (pinned tag — see Dockerfile comments) |

## Image base

Built `FROM gnzsnz/ib-gateway:<tag>`. The pinned tag is in the Dockerfile
and is bumped manually after re-running the smoke test against the new
version. Do **not** revert to `:stable` — see ADR-040 Consequences.

## Env contract

Set on the compose service (local) or the Railway service (deployed). The
full contract is in `docker-compose.yml` and `backend/.env.example`. The
non-obvious ones:

- `READ_ONLY_API=no` — image default is `yes`; without this `placeOrder`
  is a silent no-op.
- `TWS_ACCEPT_INCOMING=accept` — auto-confirms IBKR's per-connection
  "incoming client" dialog that IBC can't auto-click.
- `EXISTING_SESSION_DETECTED_ACTION=primary` — without this, headless
  login hangs forever on the "Existing session detected" dialog.

## Port mapping (DO NOT change without reading ADR-040 gotcha #2)

Local Docker: `host:4002 → container:4004`. Gateway binds `127.0.0.1:4002`
inside the container only; gnzsnz's bundled `socat` listens on `:4004` and
relays. Mapping `host:4002 → container:4002` produces a TCP-accept-then-
API-handshake-timeout symptom that is exceedingly hard to debug from logs
alone.

Railway: sibling services connect to `ib-gateway.railway.internal:4004`
directly — no port-mapping config needed.

## IBC config-template patch (DO NOT remove without re-reading ADR-040 gotcha #7)

The `gnzsnz/ib-gateway:10.45.1e` upstream ships an IBC `config.ini.tmpl`
whose three required API options either render to empty values via
`envsubst` (no matching env var in the image) or are literal blanks:

- `OverrideTwsApiPort=`                                     (literal empty)
- `AcceptIncomingConnectionAction=${TWS_ACCEPT_INCOMING}`   (envsubst — works via compose env)
- `AllowBlindTrading=${ALLOW_BLIND_TRADING}`                (envsubst — no env set, renders empty)

Without `OverrideTwsApiPort=4002` and `AllowBlindTrading=yes` in the live
config, Gateway never opens the API listener on a fresh boot — symptom is
a healthcheck loop of `connect(... 127.0.0.1:4002): Connection refused/timed out`
while IBC's log claims `Configuration tasks completed`.

The `Dockerfile` strips CRLF line-endings (the upstream `.tmpl` is DOS-
encoded so `^...=$` patterns don't match raw) and applies three `sed -i`
substitutions in place. The patch is idempotent. The companion gate is
`scripts/verify_ibgw_config.sh` — runs `grep -qxF` for each literal line
and exits 1 if any drifts away.

When bumping the gnzsnz tag in the future, re-verify the sed patterns
still match the upstream template's line shape; tag bumps occasionally
reshape variable names or whitespace. ADR-040 gotcha #7 has the full
triage history and the dead-end paths to avoid.
