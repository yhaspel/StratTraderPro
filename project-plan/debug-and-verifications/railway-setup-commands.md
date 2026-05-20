# Railway setup commands for the `ib-gateway` service

**Audience.** Yuval (operator). After the M04 Phase A close-out on 2026-05-15.

**Current state (audited 2026-05-15 17:30 IDT via `railway variable list`):**

| Environment | Status |
|---|---|
| `staging` | ✅ All 9 contract variables already set. No action needed. |
| `production` | ❌ Zero contract variables set; only Railway's auto-injected `RAILWAY_*` metadata. **Action needed.** |

So this run is **production-only**.

## Prerequisites — already confirmed in this session

- `railway` CLI v4.40.0 installed at `/opt/homebrew/bin/railway`.
- Logged in as `yuval3000@gmail.com` (`railway whoami` succeeds).
- Project `StratTraderPro` linked.
- `ib-gateway` service exists in both environments.

If any of those drift, re-run the four-line block under "Pre-flight checks" at the bottom of this file.

## Command — set all 8 non-secret variables on production in one shot

Run from the repo root in your terminal. `--skip-deploys` defers the redeploy until the password is also set, so you don't trigger 9 separate deploys.

```bash
railway variable set \
  --service ib-gateway \
  --environment production \
  --skip-deploys \
  TWS_USERID=yuval3000 \
  TRADING_MODE=paper \
  READ_ONLY_API=no \
  BYPASS_WARNING=yes \
  TWS_ACCEPT_INCOMING=accept \
  RELOGIN_AFTER_TWOFA_TIMEOUT=yes \
  EXISTING_SESSION_DETECTED_ACTION=primary \
  TIME_ZONE=Asia/Jerusalem
```

Expected output: `Set 8 variable(s) for service ib-gateway` (or similar — v4 wording varies).

## Command — set `TWS_PASSWORD` via stdin (keeps it out of shell history)

Pick one of the two options below. **Don't** put the literal password on the command line — Railway CLI v4's `--set "TWS_PASSWORD=…"` legacy form would leak it into `.zsh_history` and the process listing.

### Option A — paste into stdin (safest from terminal)

```bash
railway variable set \
  --service ib-gateway \
  --environment production \
  --skip-deploys \
  --stdin TWS_PASSWORD
```

The CLI will read from stdin. Paste the password (the same one in staging — your 1Password vault has it), press `Enter`, then `Ctrl-D` to end input. The password never appears as a shell argument.

### Option B — Railway dashboard (safest from credential manager)

1. <https://railway.app> → `StratTraderPro` → `production` → `ib-gateway` → `Variables`.
2. **New Variable** → `TWS_PASSWORD` → paste from 1Password → Save.
3. Skip the redeploy prompt if it appears; we'll trigger it once after `railway up` below.

## Verify (after both commands above)

```bash
railway variable list \
  --service ib-gateway \
  --environment production \
  --kv \
  | grep -E "^(TWS_|TRADING_|READ_ONLY|BYPASS|RELOGIN|EXISTING_SESSION|TIME_ZONE)" \
  | sort
```

Expected: 9 lines exactly, matching the staging output. `TWS_PASSWORD` value will print as its actual value (Railway CLI does **not** mask secrets in `variable list`) — close the terminal when you're done.

## Deploy

```bash
railway up --service ib-gateway --environment production
```

This triggers one redeploy with all 9 variables active. Watch logs:

```bash
railway logs --service ib-gateway --environment production | head -50
```

Expect to see, in order, `Starting Xvfb server` → `Starting IBC in paper mode` → `IBC: Login has completed` → `IBC: Configuration tasks completed` → `IBC: TWS API socket port is already set to 4002`. Cold start on Railway is typically 30-90s.

## Sanity-test the production API listener

From a sibling Railway service (e.g. SSH into `backend-production`) or via `railway run`:

```bash
railway run --service backend --environment production -- python3 -c "
import socket
s = socket.socket()
s.settimeout(5)
s.connect(('ib-gateway.railway.internal', 4004))
print('TCP OK')
s.close()
"
```

This proves the socat relay on port 4004 is reachable from sibling services. The actual ib_insync API handshake will only succeed if the paper account has had a recent web SSO touch — see `docs/runbooks/ib-gateway-reauth.md` for the dormancy mitigation procedure (weekly login at IBKR SSO portal).

## Pre-flight checks (run only if any of the above fails)

```bash
which railway && railway --version    # expect v4.x at /opt/homebrew/bin/railway
railway whoami                         # expect Yuval Haspel
railway status                         # expect Project: StratTraderPro
```

If `railway --version` is older than v4, the `variable set` subcommand may not exist; upgrade via `brew upgrade railway` first. The older v3 syntax (`railway variables --set "K=V" ...`) still works in v4 but is marked legacy in `--help` and may be removed in v5.
