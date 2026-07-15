# 03 — Apply the fix for the missing IBC overrides

**Goal.** Get the three required IBC overrides (`AcceptIncomingConnectionAction=accept`, `AllowBlindTrading=yes`, `OverrideTwsApiPort=4002`) into the **live** `/home/ibgateway/ibc/config.ini` such that `./scripts/verify_ibgw_config.sh` exits 0.

The fix path is selected by the cause identified in `02-diagnose-config-render.md`.

## Path A — Build skip (RUN didn't execute)

```bash
# 1. Inspect the current Dockerfile for any USER mis-ordering
cat docker/ib-gateway/Dockerfile

# 2. Ensure the RUN is between USER root and USER ibgateway, no extra USER lines in between.
#    The Dockerfile should look like:
#       FROM gnzsnz/ib-gateway:10.45.1e
#       USER root
#       RUN if ! grep -q "^AcceptIncomingConnectionAction=" /home/ibgateway/ibc/config.ini.tmpl; then \
#             printf '\n# ...\nAcceptIncomingConnectionAction=accept\n...' >> /home/ibgateway/ibc/config.ini.tmpl ; \
#             echo "[strattraderpro] patched..." ; \
#           else \
#             echo "[strattraderpro] no-op" ; \
#           fi
#       USER ibgateway
#    If the structure is different, fix it.

# 3. Rebuild with verbose output and capture
docker compose --profile ibkr-spike build --no-cache --progress=plain ib-gateway 2>&1 | tee /tmp/build.log
grep -E "patched IBC template|already patched" /tmp/build.log

# 4. Recreate
docker compose --profile ibkr-spike down
docker compose --profile ibkr-spike up -d ib-gateway

# 5. Wait for login
timeout 180 bash -c 'while ! docker compose logs --tail=200 ib-gateway 2>/dev/null | grep -q "Login has completed"; do sleep 3; done'

# 6. Verify
./scripts/verify_ibgw_config.sh
```

If the verify script now passes, Path A is done. If not, the diagnosis was wrong — return to `02-diagnose-config-render.md`.

## Path B — Permission deny

Unlikely with the existing Dockerfile (it switches to USER root before the RUN). If you somehow land here:

```bash
# Force the template owner before write
# (Edit docker/ib-gateway/Dockerfile to chmod/chown explicitly):
# RUN chmod 0644 /home/ibgateway/ibc/config.ini.tmpl && \
#     printf '...' >> /home/ibgateway/ibc/config.ini.tmpl
```

Then rebuild + recreate + verify.

## Path C — Render strips additions

This is the most likely cause given today's evidence. The gnzsnz render script (typically `/root/scripts/run.sh` or `/home/ibgateway/scripts/run_*.sh` in this image family) reads the `.tmpl` and writes only specific recognized lines to `config.ini` — anything not in its known-keys list is silently dropped.

**Two fix options, pick one:**

### Option C.1 — Append after render (recommended, less intrusive)

Bake a startup wrapper into the Dockerfile that runs gnzsnz's entrypoint, polls for the rendered `config.ini`, and appends the missing lines as soon as it appears (before IBC starts reading it).

```bash
# Write the wrapper script
mkdir -p docker/ib-gateway/overrides
cat > docker/ib-gateway/overrides/append-overrides.sh << 'EOF'
#!/bin/bash
# Append missing IBC options to the freshly-rendered config.ini.
# Fix for gnzsnz 10.45.1e regression where AcceptIncomingConnectionAction
# isn't in the render allowlist. See ADR-040 Findings.

set -e
CFG=/home/ibgateway/ibc/config.ini

# Run in the background — poll for the file to appear post-render
(
  for i in $(seq 1 120); do
    if [ -f "$CFG" ] && grep -q "^TradingMode=" "$CFG"; then
      if ! grep -q "^AcceptIncomingConnectionAction=" "$CFG"; then
        {
          echo ""
          echo "# StratTraderPro override (ADR-040 fix for gnzsnz 10.45.1e)"
          echo "AcceptIncomingConnectionAction=accept"
          echo "AllowBlindTrading=yes"
          echo "OverrideTwsApiPort=4002"
        } >> "$CFG"
        echo "[strattraderpro-fix] config.ini patched at $(date -u +%FT%TZ)" >&2
      fi
      break
    fi
    sleep 0.5
  done
) &

# Exec the upstream entrypoint. Discover its path; common locations:
for entry in /root/scripts/run.sh /usr/local/bin/run.sh /entrypoint.sh /run.sh; do
  if [ -x "$entry" ]; then
    exec "$entry" "$@"
  fi
done
echo "[strattraderpro-fix] could not find upstream entrypoint" >&2
exit 99
EOF
chmod +x docker/ib-gateway/overrides/append-overrides.sh

# Update the Dockerfile to use this wrapper as the ENTRYPOINT
cat > docker/ib-gateway/Dockerfile << 'DOCKERFILE'
FROM gnzsnz/ib-gateway:10.45.1e

# StratTraderPro entrypoint wrapper.
# Appends IBC config overrides that gnzsnz 10.45.1e omits, after the upstream
# render step writes /home/ibgateway/ibc/config.ini. The polling runs in the
# background while the upstream entrypoint proceeds normally; the timing
# window is ample because IBC reads config.ini just before invoking the
# IB Gateway JVM, well after the render. See ADR-040 Findings.
#
# Pinned tag: 10.45.1e — same version :stable resolved to during the
# 2026-05-09 Day-1 spike. Bump procedure documented in this file's comments.

USER root
COPY docker/ib-gateway/overrides/append-overrides.sh /usr/local/bin/append-overrides.sh
RUN chmod +x /usr/local/bin/append-overrides.sh

ENTRYPOINT ["/usr/local/bin/append-overrides.sh"]
USER ibgateway
DOCKERFILE
```

Rebuild + recreate + verify:

```bash
docker compose --profile ibkr-spike build --no-cache ib-gateway
docker compose --profile ibkr-spike down
docker compose --profile ibkr-spike up -d ib-gateway
timeout 180 bash -c 'while ! docker compose logs --tail=200 ib-gateway 2>/dev/null | grep -q "Login has completed"; do sleep 3; done'

# Allow the background patcher to run (it polls for ~60s, but the file appears within seconds)
sleep 10

./scripts/verify_ibgw_config.sh
```

If verify passes, Path C.1 is done.

If verify fails because the script reports `OverrideTwsApiPort=4002` is missing while the other two are present, that means the line was added but a *different* `OverrideTwsApiPort=` (empty value) is also present and the verify is grepping the wrong one. Fix by switching from append-only to "replace-if-exists, append-if-not":

Edit `docker/ib-gateway/overrides/append-overrides.sh` so the patch block uses `sed -i` to replace any existing `OverrideTwsApiPort=` line, then append the others. Re-build and re-verify.

If verify fails because the wrapper couldn't find the upstream entrypoint (exit 99 in container logs), inspect the running container's actual entrypoint binary:

```bash
docker run --rm --entrypoint sh gnzsnz/ib-gateway:10.45.1e -c 'cat /etc/passwd; echo ---; ls -la /'
```

Pin the exact path discovered and update the `for entry in` loop in `append-overrides.sh`.

### Option C.2 — Patch the render script directly (more invasive)

Only use if Option C.1 has a fundamental issue (e.g., upstream entrypoint can't be exec'd from our wrapper, or timing window is fragile).

Find the upstream render script identified in `02-diagnose-config-render.md` step 4. Bake a `sed -i` into the Dockerfile that modifies that script to include our three options in its allowlist. This is more brittle because the path may change on gnzsnz upstream rebuilds — that's why C.1 is preferred.

## Path D — Wrong template path

If `02-diagnose-config-render.md` revealed gnzsnz reads a different template (e.g., `/root/ibc/config.ini.template`), update the Dockerfile's RUN to target that path instead. Rebuild + recreate + verify.

## Verify

`./scripts/verify_ibgw_config.sh` exits 0 and prints:

```
OK: /home/ibgateway/ibc/config.ini has all 3 required IBC overrides.
```

If this is true, this file is done.

## FALLBACK

If neither C.1 nor C.2 nor any explicit cause-based path makes the verify script pass, escalate to:

- Bind-mounting a fully-formed `config.ini` over gnzsnz's render entirely. This requires reproducing gnzsnz's env-var substitution ourselves. Generate the substituted file in a `pre-up` script or via a sidecar init container.
- Or, switch base image. The most-promising community fork is `extrange/ibkr-docker` — has a different IBC config rendering approach and may sidestep this whole class of issue. Cost: ~2 hours of re-validation.

Update memory with whichever path you took and why before proceeding.

## NEXT

Read `04-verify-smoke-connect.md`.
