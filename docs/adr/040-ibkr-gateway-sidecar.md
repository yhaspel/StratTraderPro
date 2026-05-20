# ADR-040 — IB Gateway sidecar on Railway

**Date:** 2026-05-09 (spike); 2026-05-15 (close-out — see Findings)
**Status:** Accepted (2026-05-15 — see Findings)
**Milestone:** M04 — Webhook Ingest + IBKR Paper

> Closed out by the M04 Phase A spike rerun on 2026-05-15. Assumptions
> A1, A2 (including real fill capture during RTH at 17:15 IST — AAPL @
> $299.15, fill_count=1), and A4 are fully verified. A3 (reconnect) is
> verified-with-constraint: under `gnzsnz/ib-gateway:10.45.1e` Gateway
> allows exactly one TWS-API session per process boot — every reconnect
> within the same Gateway lifetime silently drops the API handshake
> regardless of clientId or wait time. The broker adapter (M04 plan
> §6.2) must use container-per-session or Gateway-restart-on-disconnect.
> The Decision to "Promote with changes" stands. See
> `project-plan/debug-and-verifications/handoff-status.md` for the
> close-out evidence trail.

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

Smoke run on 2026-05-09, Saturday (markets closed).

- **A1 (boot):** ✅ passed. Container reaches "Login has completed" in ~5s after start; full IB API ready ~30s in. Healthcheck `bash /dev/tcp 4004` flips to healthy within first 15s interval after that. Cold start observed: ~35s wall clock from `up -d` to API-ready (well under the 180s `start_period`).
- **A2 (connect + order):** ✅ passed (with one caveat). `ib_insync` connected in 0.5s, account summary returned 80 rows from paper account `DUN167649`, AAPL 1-share MKT order accepted (`brokerOrderId=5`, status `PreSubmitted`). Step-3 caveat: IBKR rejected the first send with `Error 10349: Order TIF was set to DAY based on order preset` and ib_insync auto-resubmitted it (visible in log) — Gateway accepted the retry. Worth handling explicitly in the M04 broker adapter (catch 10349, set TIF=DAY in the OrderRequest before the first send).
- **A2 partial — fill (Step 4):** ✅ verified on 2026-05-15 RTH rerun. Smoke with clientId 310 (TIF=DAY) placed a 1-share AAPL MKT buy at 17:15:08 IDT, IBKR routed it ARCA, filled in 401 ms at **$299.15**, `cumQty=1.0`, `execId=0000e0d5.6a071c95.01.01`, commission $1.00. `fill_count=1`. Full SpikeResult is in `project-plan/debug-and-verifications/evidence-20260515/smoke-rth-1234pass-5constrained.log`. **Caveat carried into production code:** the smoke had to set `tif="DAY"` explicitly on the `MarketOrder` constructor. Without it, IBKR's paper-account order preset rejects the first send with `Error 10349: Order TIF was set to DAY based on order preset`. This was already noted as a 2026-05-09 finding; the smoke script now bakes the workaround in (`scripts/spike_ibkr_smoke.py` STEP 3 has the comment + `tif="DAY"` literal). The M04 broker adapter must do the same.
- **A3 (reconnect):** ⚠️ verified-with-constraint on 2026-05-15. The original spike contract was "same `clientId` reconnect after a 3-second disconnect works". That contract fails in `gnzsnz/ib-gateway:10.45.1e`: reconnect on the same `clientId` TimeoutErrors at the API handshake, and so does reconnect on `clientId + 1` immediately after, and so does any new connection (with any `clientId`) after the first session in a Gateway process lifetime has disconnected. **Gateway allows exactly one successful TWS-API session per process boot under this image.** Verified by three independent paths during the smoke: smoke STEP 5 same-clientId (failed), smoke STEP 5 rotated-clientId (failed), single-shot `clientId=320` 30 seconds after a clean disconnect (failed). The fix is **not** clientId rotation — the broker adapter (plan §6.2) needs container-per-session or a Gateway-restart-on-disconnect strategy. ADR-041 (forthcoming, M04 production design) should document the chosen pattern explicitly. Until then, treat each Gateway container as single-use. Whether this constraint is specific to a recently-dormant paper account (today's case — 6 days no web login) or to gnzsnz 10.45.1e in general is an open question; revisit after the account has been actively used for ~1 week.
- **A4 (Railway env model):** ✅ passed. Deployed from `gnzsnz/ib-gateway:stable` directly (Docker Image source, no GitHub build needed). Service created in Railway staging, US-East region, no public domain. 10 env vars set via Raw Editor + individual New Variable forms; credentials carried through env vars without truncation. After fixing one missing config (gotcha #6 below), `Login has completed` appeared in IBC logs ~60s after image pull. TCP probe from `backend-staging` container: `python3 -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('ib-gateway.railway.internal', 4004)); print('OK')"` returned `OK — Railway internal networking + port 4004 confirmed`. Railway's auto-enabled Private Networking proxies sibling-service traffic to any container port without per-port config — so the local-Docker socat-on-4004 trap (gotcha #2) becomes a non-event on Railway as long as smoke clients target port 4004 explicitly.

### Notes (gotchas — must carry into M04 proper)

1. **Pivoted off the from-scratch Dockerfile.** The original `eclipse-temurin + curl IBKR installer` approach was correct in spirit but blocked by **Apple-Silicon Rosetta** failing on the InstallAnywhere installer's bundled x86_64 JRE (`rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2`, exit 133). Switched to `FROM gnzsnz/ib-gateway:stable` — multi-arch image, builds in ~20s vs the failing 36s, no Rosetta involvement. The from-scratch path could still work in a Linux CI job, but for local dev on Apple Silicon, gnzsnz is the only viable option without disabling Rosetta system-wide.

2. **The `4002:4002` port mapping is a trap.** gnzsnz's image binds IB Gateway itself to **127.0.0.1:4002 only** (its `jts.ini` ships `TrustedIPs=127.0.0.1`), and a sidecar `socat` listens on **container :4004** forwarding to `127.0.0.1:4002`. If you publish host:4002 → container:4002 (the obvious mapping), external clients hit Gateway directly with the Docker bridge source IP, the TCP accept succeeds, and the API handshake is silently dropped — exact symptom is ib_insync `API connection failed: TimeoutError()` 10s after a successful TCP connect, looping forever. **Correct mapping is `host:4002 → container:4004`.** This took 4 wrong hypotheses (Login, Trusted IPs as env-var, generic env-var contract, image-version mismatch) before `ps -ef` inside the container showed `socat TCP-LISTEN:4004,fork TCP:127.0.0.1:4002`.

3. **gnzsnz env-var contract** — beyond `TWS_USERID/TWS_PASSWORD/TRADING_MODE`, the production compose service must set:
   - `TWS_ACCEPT_INCOMING=accept` (default `manual` raises a per-connection modal IBC won't auto-click)
   - `READ_ONLY_API=no` (default `yes` would make `placeOrder` a silent no-op — the spike caught this preemptively)
   - `BYPASS_WARNING=yes`, `RELOGIN_AFTER_TWOFA_TIMEOUT=yes`, `TIME_ZONE=Asia/Jerusalem`
   None of these alone fixed the handshake-timeout bug (that was the port mapping), but the M04 production sidecar needs the full set.

4. **Vestigial files.** `docker/ib-gateway/entrypoint.sh` and `docker/ib-gateway/ibc-config.ini` were authored for the from-scratch image and aren't used by the gnzsnz base. Removed on 2026-05-15 as part of the close-out promotion (see `project-plan/debug-and-verifications/08-promote-artifacts.md`).

5. **Israel-account / unified-login note.** Yuval's account is IBKR Israel (unified live/paper). `TWS_USERID/TWS_PASSWORD` take the live credentials; `TRADING_MODE=paper` is the headless equivalent of the web-login Live/Paper toggle. Login completed without 2FA prompt — IBKR's Secure Login System is not enforced for paper-mode logins on this account, despite the runbook's prerequisites section anticipating it might be.

6. **`EXISTING_SESSION_DETECTED_ACTION` is unset by default in gnzsnz** and must be set explicitly. With it blank, IBC pops the "Existing session detected" dialog and waits forever for a human click — login never completes, and the service appears Active in Railway because the container is up but the API never goes live. First Railway boot of `ib-gateway` failed precisely on this: IBC reached the dialog at 16:24:10 and stalled silently. Setting `EXISTING_SESSION_DETECTED_ACTION=primary` (take over the existing session) resolved it on the next deploy. Add to the production env-var contract in gotcha #3. Acceptable values: `primary` (take over, recommended for headless), `secondary` (read-only attach), `manual` (default-ish — wait for human, never use headlessly).

7. **gnzsnz/ib-gateway:10.45.1e ships an IBC `config.ini.tmpl` whose three API options either render empty or are inert literals.** Discovered 2026-05-15 during the close-out rerun. Concretely the template's three relevant lines are:

   ```
   OverrideTwsApiPort=                                    # literal empty
   AcceptIncomingConnectionAction=${TWS_ACCEPT_INCOMING}  # envsubst — works via compose env
   AllowBlindTrading=${ALLOW_BLIND_TRADING}               # envsubst — no env set, renders empty
   ```

   `apply_settings()` in `/home/ibgateway/scripts/common.sh` runs `envsubst <tmpl >config.ini` (whole-file copy with variable substitution). So `AcceptIncomingConnectionAction=accept` works because `TWS_ACCEPT_INCOMING=accept` is set in `docker-compose.yml`, but `OverrideTwsApiPort=` lands in the live config as a literal blank, and `AllowBlindTrading=` likewise renders empty because no env var feeds it. **Result:** even with the compose env contract from gotcha #3 fully applied, Gateway never opens the API listener on a fresh first boot — symptom is socat looping `connect(... 127.0.0.1:4002, 16): Connection refused/timed out` while IBC's log claims `Configuration tasks completed`.

   **An append-if-missing Dockerfile guard is a trap here.** The naïve fix (`if ! grep -q "^AcceptIncomingConnectionAction=" tmpl; then printf '...' >> tmpl; fi`) silently no-ops because the templated line `AcceptIncomingConnectionAction=${TWS_ACCEPT_INCOMING}` matches the grep prefix. We tried this approach first; the patch never landed in the live config and `scripts/verify_ibgw_config.sh` kept failing.

   **The fix in `docker/ib-gateway/Dockerfile` is sed-based.** First a CR-stripping pass (the upstream `.tmpl` is CRLF-encoded, so `^...=$` patterns don't match), then three literal substitutions onto the templated lines:

   ```dockerfile
   RUN sed -i 's/\r$//' /home/ibgateway/ibc/config.ini.tmpl \
    && sed -i \
         -e 's|^OverrideTwsApiPort=$|OverrideTwsApiPort=4002|' \
         -e 's|^AllowBlindTrading=\${ALLOW_BLIND_TRADING}$|AllowBlindTrading=yes|' \
         -e 's|^AcceptIncomingConnectionAction=\${TWS_ACCEPT_INCOMING}$|AcceptIncomingConnectionAction=accept|' \
         /home/ibgateway/ibc/config.ini.tmpl
   ```

   The substitutions are idempotent — re-running them on an already-patched template is a no-op because the from-patterns no longer match. `scripts/verify_ibgw_config.sh` is the post-build regression gate: it `grep -qxF`s each literal line in `/home/ibgateway/ibc/config.ini` and exits 1 (with a fix-command hint) if any is missing. Bumping the gnzsnz tag in the future requires re-running this script and re-validating the sed patterns still match the upstream template's line shape.

   **Other dead-end paths explored on 2026-05-15 (all documented to save the next reader an hour):**
   - `JAVA_TOOL_OPTIONS=-Djava.net.preferIPv4Stack=true` via compose env — gets clobbered by `ibcstart.sh:480` which sets `JAVA_TOOL_OPTIONS=` before invoking the JVM. Don't try this.
   - Appending `-D...` flags to `ibgateway.vmoptions` — silently dropped by `ibcstart.sh`'s vmoptions parser which strips `^-D` lines (it adds its own `-D` flags downstream).
   - Enabling IBC `CommandServerPort=7462` and invoking `enableapi.sh` after login — Gateway returns `ERROR ENABLEAPI is not valid for the IB Gateway`. The ENABLEAPI command is TWS-only; the Gateway's API listener has no equivalent runtime toggle.
   - `xdotool windowkill` against the hidden `Pending Tasks` / `Login Messages` JFrames — crashed the JVM (exit 137). `xdotool windowclose` (WM_DELETE_WINDOW) is the polite alternative and did dismiss them, but those dialogs are not the API blocker.
   - Patching `jts.ini.tmpl` to set `TrustedIPs=127.0.0.1,::1,::ffff:127.0.0.1` — IBC overwrites it on every boot with its own minimal set (`IBC: Rewriting existing /home/ibgateway/Jts/jts.ini`). The template patch never lands in live state.

   **One side patch that DOES propagate correctly (kept in the Dockerfile as defense in depth):** set `TrustedTwsApiClientIPs=127.0.0.1,::1,::ffff:127.0.0.1` in IBC's `config.ini.tmpl`. IBC reads that and writes the merged set into jts.ini's `TrustedIPs` — verified by running container with `grep '^TrustedIPs' /home/ibgateway/Jts/jts.ini` showing `TrustedIPs=127.0.0.1,127.0.0.1,::1,::ffff:127.0.0.1`. This isn't what was causing the 2026-05-15 residual TimeoutError (the symptom persisted with all four forms trusted), but it's the right way to expand Gateway's trust list if a future scenario needs it. Sed pattern in `docker/ib-gateway/Dockerfile`: `-e 's|^TrustedTwsApiClientIPs=$|TrustedTwsApiClientIPs=127.0.0.1,::1,::ffff:127.0.0.1|'`.

8. **IBKR paper-account preset rejects MKT orders without an explicit TIF.** Verified on both the 2026-05-09 spike and the 2026-05-15 close-out. `ib.placeOrder(contract, MarketOrder("BUY", 1))` lands at Gateway, gets a `brokerOrderId`, transitions to `PendingSubmit` and then immediately `Cancelled` with `Error 10349: Order TIF was set to DAY based on order preset.` ib_insync 0.9.86 does NOT auto-resubmit reliably (the 2026-05-09 finding showed an auto-resubmit; 2026-05-15 did not — behaviour is conditional on flags not worth digging into). The fix is to set `tif="DAY"` upfront on every `MarketOrder` (and presumably `LimitOrder`) the adapter places. `scripts/spike_ibkr_smoke.py` STEP 3 has the workaround baked in with a pointing comment. The M04 broker adapter (`apps/brokers/ibkr` per plan §6.2) must do the same.

9. **IBKR paper-account 6-day web-login dormancy.** Verified 2026-05-15 as the actual root cause of the morning's TimeoutError loop. After ~5–6 days with no SSO web-portal login on the paper account, IBKR's auth backend silently disables headless TWS-API access for that user. Headless `ibcstart.sh` username/password login still completes ("Login has completed", Gateway connects to IBKR backend, status pane shows green "API Server: connected") — but Gateway never spawns its TWS-API listener thread, port 4002 binds at kernel level with no application-layer reader, every `ib_insync.connect()` gets `Connected` (TCP) then `API connection failed: TimeoutError()` 10 s later. The fix is a single web-portal login at <https://www.interactivebrokers.com/sso/Login>, switch to Paper view, wait ~5 min for propagation. Single login is enough; no toggle to flip. Operator-side weekly login is the M04 interim mitigation (documented in `docs/runbooks/ib-gateway-reauth.md`); M04A's OAuth/REST transport removes this property entirely.

10. **Gateway allows exactly one TWS-API session per process boot.** Discovered 2026-05-15 during STEP 5 of the RTH smoke. After the first successful client session disconnects, every subsequent connection on port 4002 — same `clientId`, rotated `clientId`, 3-second wait, 30-second wait — silently drops the API handshake. Verified by three independent paths (smoke STEP 5 same-clientId, smoke STEP 5 rotated-clientId, single-shot `clientId=320` 30 s after disconnect). Container-restart resets it. **M04 plan §6.2 broker adapter must use Gateway-per-session** — either container-per-deploy (Railway worker-per-deploy makes this cheap) or container-restart-on-disconnect for the local-dev path. M04A's REST/WebSocket transport has no equivalent constraint.

## Decision

**Promote with changes.** All four assumptions hold under the gnzsnz topology, with one residual gate (A2 Step-4 fill capture + A3 same-clientId reconnect, both pending the 2026-05-15 RTH rerun — see Findings + `project-plan/debug-and-verifications/handoff-status.md`). Promote `docker/ib-gateway/Dockerfile` (pinned `FROM gnzsnz/ib-gateway:10.45.1e`) plus the env-var contract documented below into M04 proper as the production sidecar. The shape change vs. the spike's original from-scratch design:

- **Image source** changes from custom `eclipse-temurin + IBC + IB Gateway installer` → `FROM gnzsnz/ib-gateway:stable` (multi-arch, sidesteps Apple-Silicon Rosetta failure on the InstallAnywhere installer).
- **Vestigial spike files** (`docker/ib-gateway/entrypoint.sh`, `ibc-config.ini`) are unused by the gnzsnz base; they get deleted at promotion time, not kept.
- **Production env-var contract** (the union of all gotchas):
  - `TWS_USERID`, `TWS_PASSWORD` — per-user, encrypted at rest in M04 proper (KEK-wrapped DEK), not the env model used here.
  - `TRADING_MODE=paper` — paper-only in M04; live deferred to M13+.
  - `READ_ONLY_API=no` — must override gnzsnz default (`yes`) or `placeOrder` is a silent no-op.
  - `BYPASS_WARNING=yes`, `TWS_ACCEPT_INCOMING=accept`, `RELOGIN_AFTER_TWOFA_TIMEOUT=yes`.
  - `EXISTING_SESSION_DETECTED_ACTION=primary` — without this, headless login hangs (gotcha #6).
  - `TIME_ZONE=Asia/Jerusalem`.
- **Port mapping**: local Docker uses `host:4002 → container:4004`; Railway sibling services connect to `ib-gateway.railway.internal:4004` directly (no port mapping config needed in Railway).
- **Per-user routing** (plan §6.2): one Gateway-per-user-on-demand vs. shared-Gateway-with-Redis-locks. Today's RTH finding that Gateway allows exactly one TWS-API session per process boot (Findings A3) effectively forecloses the shared-Gateway-with-Redis-locks option — there's nothing to multiplex once the first session ends. M04 §6.2 ships **Gateway-per-session** (container-per-deploy on Railway, container-restart-on-disconnect locally). Multi-user routing is M04 proper work; truly multi-user broker concurrency lands in **M04A** (`project-plan/04A-IBKR-Web-API.md`), where the REST/OAuth transport has no per-process session limit.

A2 Step 4 + A3 verification will close out during the 2026-05-15 RTH rerun (16:30–23:00 IST): re-execute `scripts/spike_ibkr_smoke.py` against either local Docker or the Railway service (probably local — easier than `railway ssh + pip install ib_insync` dance), confirm both `fill_count=1` and `reconnect_ok=True`, then replace the corresponding A2/A3 bullets in Findings with the verbatim `SPIKE RESULT` numbers. The Status flip to Accepted at the top of this ADR is conditioned on those bullets becoming `Verified`.

## Consequences

**Positive:**
- IB Gateway sidecar topology validated end-to-end on Railway. M04 broker-adapter work can begin once the 2026-05-15 RTH rerun confirms A2 Step 4 + A3 — no architectural blockers remain.
- The four-assumption framing surfaced six concrete gotchas that would have otherwise eaten Days 2-3 of M04. All now in the env-var contract or the runbook triage table.
- gnzsnz gives us multi-arch image, IBC pre-installed, and a maintained source we can pin without re-building. Cuts our maintenance burden vs. the from-scratch path.

**Negative:**
- Reliance on a community-maintained image (`gnzsnz/ib-gateway`). If the maintainer abandons it, we'd need to either fork or fall back to the from-scratch path on a Linux-only build host.
- Pinning to `:stable` rather than a specific version digest means a published image-tag rebuild upstream could change behavior unexpectedly. M04 production should pin to a specific version tag (look at https://hub.docker.com/r/gnzsnz/ib-gateway/tags for the current "good" version) — discharged on 2026-05-15 by pinning to `10.45.1e` explicitly in the Dockerfile.
- `EXISTING_SESSION_DETECTED_ACTION=primary` means the Railway Gateway will silently kick out any other live IBKR session with the same credentials. Acceptable for paper. For live trading (M13+), this needs revisiting because we don't want our automated session to disconnect a human trader who's logged in via mobile.
- Vestigial spike files (`entrypoint.sh`, `ibc-config.ini`) need deletion at promotion. Tracked as a cleanup item — done 2026-05-15 (see Findings note #4).
- **Paper-account dormancy.** IBKR silently disables headless TWS-API access on a paper account after ~5–6 days without a web-portal touch (root cause of today's morning TimeoutError loop — verified by SSO web-login restoring the API listener instantly). Interim mitigation is operator-side: a weekly login at <https://www.interactivebrokers.com/sso/Login> is documented as the first triage step in `docs/runbooks/ib-gateway-reauth.md`. **Durable fix is M04A** (`project-plan/04A-IBKR-Web-API.md`) — the Client Portal Web API with OAuth doesn't have this dormancy property. Reserved as a fallback (and deferred unless M04 paper-trading shows weekly is too brittle): an automated Playwright "heartbeat web login" Celery beat task.
- **Gateway one-session-per-process-boot constraint.** Verified during 2026-05-15 RTH smoke (see Findings A3). Every TWS-API reconnect within the same Gateway lifetime silently drops the handshake, regardless of `clientId` or wait time; only a fresh Gateway process accepts a new client. M04 plan §6.2 broker adapter must use container-per-session or Gateway-restart-on-disconnect to recover from network blips. M04A removes this constraint entirely (REST/WebSocket transport has no equivalent), reinforcing M04A as the durable architecture.

## Decision carryover (2026-05-15): Phase B ships on TWS Socket API; M04A migration tracked

Documented in detail in `project-plan/plan-progress-tracker.md` Phase 04 "Decision (2026-05-15)" block. Summary: M04 ships on this gateway substrate as planned; the operator-weekly-login workaround + container-per-session pattern are the M04-era mitigations for the two account-side constraints above; the durable fix is M04A (already scoped at `project-plan/04A-IBKR-Web-API.md`). The `BrokerAdapter` protocol layer that the bulk of M04 §6 builds is reused unchanged by M04A — only the IBKR transport implementation under `apps/brokers/ibkr` gets swapped for `apps/brokers/ibkr_webapi` — so this is sequencing, not throwaway work. **Action item:** kick off M04A's IBKR developer-portal enrollment (`04A-IBKR-Web-API.md` §5.1, 5–10 business-day approval lead time) as soon as M04 §6.2 lands so the IBKR-side clock runs in parallel.

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
