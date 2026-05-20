# IB Gateway sidecar — M04
#
# Uses the community-maintained gnzsnz image instead of installing IB
# Gateway + IBC from scratch — sidesteps the Apple-Silicon/Rosetta failure
# on the InstallAnywhere installer. See docs/adr/040-ibkr-gateway-sidecar.md.
#
# Image contract (env vars, ports, healthcheck) is identical to what the
# previous from-scratch Dockerfile exposed:
#   TWS_USERID, TWS_PASSWORD, TRADING_MODE (paper only — enforced by compose)
#   4002 = paper API, 5900 = VNC (only when DEBUG_VNC=1 is set)
#
# Pinned to a specific tag (not :stable) so an upstream image rebuild can
# never silently change behavior under us. ADR-040 Consequences flagged
# `:stable` drift as a known risk; this pin discharges it.
#
# Tag history:
#   10.45.1e — current pin. Same version :stable resolved to during the
#              2026-05-09 Day-1 spike. Bump by:
#                1. Picking a newer tag from
#                   https://hub.docker.com/r/gnzsnz/ib-gateway/tags
#                2. Re-running scripts/spike_ibkr_smoke.py end-to-end.
#                3. Re-running scripts/verify_ibgw_config.sh against the
#                   new build to confirm the sed patches below still
#                   match the upstream template's line shape.
#                4. Recording the new working version here.

FROM gnzsnz/ib-gateway:10.45.1e

# IBC config template patch — fix for gnzsnz 10.45.1e "API never opens" gotcha.
#
# The upstream /home/ibgateway/ibc/config.ini.tmpl already contains the three
# settings we need, but two of them either render to empty values via envsubst
# (no matching env var set in the image) or are literal blanks:
#
#   OverrideTwsApiPort=                                    ← literal empty
#   AllowBlindTrading=${ALLOW_BLIND_TRADING}               ← envsubst → empty
#   AcceptIncomingConnectionAction=${TWS_ACCEPT_INCOMING}  ← envsubst → "accept" via compose
#
# Empty OverrideTwsApiPort means IBC never tells Gateway which port to listen
# on, and Gateway 10.45.1e ships with the API listener disabled by default;
# socat then loops "Connection timed out" trying to forward to 127.0.0.1:4002.
#
# We substitute the three lines to literal values via sed. This is idempotent —
# re-running the sed on an already-patched template is a no-op because the
# from-patterns no longer match. We also pin AcceptIncomingConnectionAction
# to a literal value (not the env var) so the override survives if the
# compose env contract drifts.
#
# Why sed (and not append): the earlier append-if-missing approach false-
# matched on the templated AcceptIncomingConnectionAction line and silently
# skipped the patch (see ADR-040 Findings gotcha #7).
#
# scripts/verify_ibgw_config.sh runs `grep -qxF` for each literal line and
# is the regression check that keeps this patch honest.
# Important: upstream config.ini.tmpl uses CRLF (DOS) line endings. The sed
# `$` end-of-line anchor doesn't match before `\r`, so we strip CR with the
# first sed pass before the substitution passes run.
USER root
RUN sed -i 's/\r$//' /home/ibgateway/ibc/config.ini.tmpl \
 && sed -i \
      -e 's|^OverrideTwsApiPort=$|OverrideTwsApiPort=4002|' \
      -e 's|^AllowBlindTrading=\${ALLOW_BLIND_TRADING}$|AllowBlindTrading=yes|' \
      -e 's|^AcceptIncomingConnectionAction=\${TWS_ACCEPT_INCOMING}$|AcceptIncomingConnectionAction=accept|' \
      -e 's|^TrustedTwsApiClientIPs=$|TrustedTwsApiClientIPs=127.0.0.1,::1,::ffff:127.0.0.1|' \
      /home/ibgateway/ibc/config.ini.tmpl \
 && echo "[strattraderpro] IBC template patched (sed):" \
 && grep -nE '^(OverrideTwsApiPort|AllowBlindTrading|AcceptIncomingConnectionAction|TrustedTwsApiClientIPs)=' \
      /home/ibgateway/ibc/config.ini.tmpl

USER ibgateway
