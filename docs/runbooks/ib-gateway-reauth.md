# Runbook — IB Gateway sidecar (operations + re-auth)

**Last reviewed:** 2026-07-12

**Owner:** Yuval
**Status:** Production-ready (M04). Was the M04 Day-1 spike runbook; promoted 2026-05-15 per `docs/adr/040-ibkr-gateway-sidecar.md` (Status: Accepted).
**Companion docs:** `docs/adr/040-ibkr-gateway-sidecar.md` (topology rationale + gotchas), `docker/ib-gateway/Dockerfile` (image pin + IBC template patches), `docker/ib-gateway/README.md` (env contract summary), `scripts/verify_ibgw_config.sh` (config-drift gate).

## When to use this runbook

- The `ib-gateway` service shows disconnected or unhealthy on staging/prod (Railway dashboard or `docker compose ps` locally).
- IBKR-side re-auth is needed after a password rotation, paper-account dormancy lockout, or Secure Login System (SLS) toggle change.
- A new operator/developer is setting up a paper account for local smoke testing.
- A bump of the `gnzsnz/ib-gateway` pinned tag is being validated.

## Account model (Path B — unified live + paper toggle)

Most current IBKR Israel / IB Ireland accounts are unified: one username/password logs into either Live or Paper depending on a web-login toggle.

- `TWS_USERID` / `TWS_PASSWORD` carry the **live** credentials.
- `TRADING_MODE=paper` is the headless equivalent of the web-login Live/Paper toggle.
- The smoke test will see only the `DU…` paper sub-account in `accountSummary()` — this is correct.

**Critical: disable 2FA for paper sessions.** If your account uses Secure Login System (IB Key push, SMS, hardware card), headless login will hang on a push approval that IBC can't auto-confirm. IBKR lets you keep 2FA on for live and off for paper:

1. Log into <https://www.interactivebrokers.com/sso/Login>.
2. Settings → User Settings → Security → **Secure Login System**.
3. Toggle named like "Use Secure Login System for Paper Trading" → **off**. Save.
4. Wait ~5 min for propagation, then retry the sidecar boot.

If the toggle isn't visible in your portal, open an IBKR support chat: "exempt paper trading from Secure Login System for headless API access" — handled routinely.

## Env contract

The full set on the compose `ib-gateway` service (local) or the Railway `ib-gateway` service (deployed):

| Variable | Required value | Why |
|---|---|---|
| `TWS_USERID` | Live username | Authentication |
| `TWS_PASSWORD` | Live password | Authentication |
| `TRADING_MODE` | `paper` | Routes login to paper sub-account |
| `READ_ONLY_API` | `no` | Image default `yes` makes `placeOrder` a silent no-op (ADR-040 gotcha #3) |
| `TWS_ACCEPT_INCOMING` | `accept` | Auto-confirms per-client "incoming connection" dialog (ADR-040 gotcha #3) |
| `BYPASS_WARNING` | `yes` | Suppresses "API precautions" modal per connect (ADR-040 gotcha #3) |
| `RELOGIN_AFTER_TWOFA_TIMEOUT` | `yes` | 2FA-friendly auto-recovery (ADR-040 gotcha #3) |
| `EXISTING_SESSION_DETECTED_ACTION` | `primary` | Without this, headless login stalls forever on the dialog (ADR-040 gotcha #6) |
| `TIME_ZONE` | `Asia/Jerusalem` (or operator's tz) | Keeps Gateway clock aligned with IBKR |
| `DEBUG_VNC` | `0` (set to `1` only when debugging) | Exposes Gateway GUI on `:5900` |

Locally, put `TWS_USERID` / `TWS_PASSWORD` in the repo-root `.env` (gitignored); `docker-compose.yml` does the `${VAR:-}` substitution. On Railway, set them as Railway env vars on the `ib-gateway` service.

## Operating the sidecar (local Docker)

### Start

```bash
docker compose --profile ibkr-spike build ib-gateway   # only if Dockerfile changed
docker compose --profile ibkr-spike up -d ib-gateway
```

Cold start is typically 30–60s (warm 10–20s). The Docker `HEALTHCHECK` has a 180s `start_period`.

### Watch boot

```bash
docker compose logs -f ib-gateway
```

Healthy boot sequence:

1. `Starting Xvfb server` / `Starting IBC in paper mode`
2. IBC: `Login has completed`
3. IBC: `Configuration tasks completed`
4. IBC: `TWS API socket port is already set to 4002`
5. (silence — Gateway is serving the API)

### Verify

```bash
./scripts/verify_ibgw_config.sh    # asserts the three required IBC overrides
nc -zv localhost 4002              # TCP probe through the socat relay
```

If `verify_ibgw_config.sh` exits non-zero, the `docker/ib-gateway/Dockerfile` IBC-template patch isn't taking effect. Most common cause is a `gnzsnz/ib-gateway` upstream tag bump that reshaped the template's line endings or variable names — re-read `docker/ib-gateway/Dockerfile`'s sed patches and the upstream `.tmpl` shape (ADR-040 gotcha #7).

### Inspect via VNC (debug only)

Set `DEBUG_VNC=1` in `.env`, restart the container, then on macOS: `open vnc://localhost:5900` (no password). Use this only when triaging — leaving VNC exposed is a security risk.

### Stop

```bash
docker compose --profile ibkr-spike down       # remove
docker compose --profile ibkr-spike stop ib-gateway   # keep image around for next iteration
```

## Operating the sidecar (Railway)

The Railway service is a Worker (no public domain — 4002 isn't reachable from the internet). Sibling services connect via `ib-gateway.railway.internal:4004` (gnzsnz's socat port, which Railway's Private Networking proxies automatically — no per-port config needed).

To set the env contract on Railway, the canonical commands are in `project-plan/debug-and-verifications/railway-setup-commands.md` (generated at Phase A close-out).

To trigger a redeploy after env changes:

```bash
railway up --service ib-gateway
```

## Failure-mode triage

| Symptom | First check | Likely cause |
|---|---|---|
| `docker compose ps` shows `Up (unhealthy)` | `./scripts/verify_ibgw_config.sh` | If it fails, the IBC config-render patch (ADR-040 gotcha #7) isn't applied — rebuild with `--no-cache`. |
| `nc -zv localhost 4002` succeeds but `ib_insync` `API connection failed: TimeoutError()` | `docker compose exec ib-gateway ps -ef \| grep socat` should show `socat TCP-LISTEN:4004,fork TCP:127.0.0.1:4002`. Compose `ports` must be `"4002:4004"` NOT `"4002:4002"`. Also check that no >50 connect attempts ran in the last hour against the paper account — IBKR throttles, cooldown 30 min – 4 hours. | Wrong port mapping (gotcha #2) OR paper-account rate limit. |
| IBC log shows "Logging in" stuck >2 min | Open the IBKR web SSO once to clear pending session, confirm SLS is off for paper. | 2FA hang or stale web-side session. |
| IBC log shows "Existing session detected" without a follow-up | Confirm `EXISTING_SESSION_DETECTED_ACTION=primary` is on the service env. | gotcha #6. |
| `Login failed: invalid credentials` | Web-login as a sanity check via <https://www.interactivebrokers.com/sso/Login>; if web works but headless fails, password may have a `$` / `!` that compose env substitution mangled — re-quote in `.env`. | Credentials or quoting. |
| `placeOrder` returns ack with `status=Filled=0` and zero exec details | Read-only flag stuck on. Check live config: `docker compose exec ib-gateway grep ReadOnlyApi /home/ibgateway/ibc/config.ini` must be `no`. | gotcha #3. |
| Reconnect on same clientId fails | Try a different clientId. If a fresh ID works, the broker adapter needs to rotate IDs on reconnect (M04 §6.2). If even a fresh ID fails, Gateway crashed on disconnect — re-`up -d` the container and investigate. | clientId stuck OR Gateway crash. |

## Re-auth procedure

Paper accounts silently disable API access after ~5 days of zero web-login activity. Symptom: smoke STEP 1 fails with TimeoutError after a previously-working boot.

1. Log into <https://www.interactivebrokers.com/sso/Login> with the live credentials.
2. Switch to Paper in the web client. Just being logged in is enough — no orders or settings changes needed.
3. Wait ~5 min. The web login re-arms the headless API path.
4. Rerun the smoke: `python scripts/spike_ibkr_smoke.py --host localhost --port 4002 --client-id <unused>` should now pass STEP 1.

If re-auth doesn't clear it, check the rate-limit row in the triage table.

## Bumping the gnzsnz tag

The pin is in `docker/ib-gateway/Dockerfile` (search `FROM gnzsnz/ib-gateway:`). Steps:

1. Pick a newer tag from <https://hub.docker.com/r/gnzsnz/ib-gateway/tags>.
2. Update the `FROM` line and the "Tag history" comment in the Dockerfile.
3. Rebuild: `docker compose --profile ibkr-spike build --no-cache ib-gateway`. The sed-based IBC template patch should still apply — if not, the upstream template's line shape changed; re-derive the patterns by `grep`ing for `AcceptIncomingConnectionAction|AllowBlindTrading|OverrideTwsApiPort` in the new template and updating the Dockerfile sed.
4. `./scripts/verify_ibgw_config.sh` exits 0.
5. Run `scripts/spike_ibkr_smoke.py` once pre-RTH (expect STEPS 1–3 to pass, STEP 4 to time out with `fill_count=0`).
6. Run it again during US RTH (16:30–23:00 Israel time, Mon–Fri) to confirm STEPS 4 + 5 also pass.
7. Update this runbook's pin reference if needed.

## CI integration

`scripts/verify_ibgw_config.sh` is the gate. M04 production CI must:

1. Build the `ib-gateway` image as part of the smoke job.
2. Boot it under the `ibkr-spike` profile.
3. Wait for `Configuration tasks completed` in the log.
4. Exec `./scripts/verify_ibgw_config.sh` — fail the build on non-zero exit.

This catches both upstream tag drift (Dockerfile sed patterns stale) and accidental Dockerfile/compose edits that drop the IBC overrides.
